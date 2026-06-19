package mediarequestbuilder

import (
	"context"
	"testing"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

func TestMediaBuilderAppendsShadowRequest(t *testing.T) {
	msg := service.NewMessage(nil)
	msg.SetStructured(map[string]any{
		"schema_version": "v1",
		"shadow_kind":    "observed_event_projection",
		"source_kind":    "media",
		"target_key":     "media-1",
		"evidence_id":    "media-1",
		"observed": map[string]any{
			"schema_version":   "v1",
			"collector_run_id": "run",
			"source_project":   "canary",
			"capture_method":   "test",
			"captured_at":      "2026-06-18T00:00:00Z",
			"media_id":         "media-1",
			"media_kind":       "screenshot",
			"local_path":       "/mnt/data/x-research/canaries/connect-shadow/media-1.png",
			"sha256":           "sha",
			"caption":          "hello",
			"raw": map[string]any{
				"media_id":  "media-1",
				"mime_type": "image/png",
				"width":     10,
				"height":    20,
				"byte_size": 30,
			},
		},
	})
	proc := &processor{}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch) != 2 {
		t.Fatalf("batch len = %d", len(batch))
	}
	if topic, _ := batch[1].MetaGet("shadow_output_topic"); topic != webosint.ShadowMediaRequestTopic {
		t.Fatalf("topic = %q", topic)
	}
	structured, err := batch[1].AsStructured()
	if err != nil {
		t.Fatal(err)
	}
	root := structured.(map[string]any)
	if root["shadow_kind"] != "media_enrichment_request" {
		t.Fatalf("root = %#v", root)
	}
	request := root["request"].(map[string]any)
	if request["artifact_id"] != "media-1" || request["shadow_only"] != true {
		t.Fatalf("request = %#v", request)
	}
}

func TestMediaBuilderProductionModeFansOutRequests(t *testing.T) {
	msg := service.NewMessage(nil)
	msg.SetStructured(map[string]any{
		"schema_version":   "v1",
		"collector_run_id": "run",
		"source_project":   "canary",
		"capture_method":   "test",
		"captured_at":      "2026-06-18T00:00:00Z",
		"media_id":         "media-1",
		"media_kind":       "screenshot",
		"local_path":       "/mnt/data/x-research/canaries/connect-shadow/media-1.png",
		"sha256":           "sha",
		"caption":          "hello",
		"raw": map[string]any{
			"media_id":  "media-1",
			"mime_type": "image/png",
			"width":     10,
			"height":    20,
			"byte_size": 30,
		},
	})
	msg.MetaSet("source_kind", "media")
	msg.MetaSet("target_topic", webosint.MediaObservedTopic)
	msg.MetaSet("target_key", "media-1")
	msg.MetaSet("evidence_id", "media-1")

	proc := &processor{mode: "production"}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch) != 4 {
		t.Fatalf("batch len = %d", len(batch))
	}
	wantTopics := []string{webosint.MediaEnrichmentTopic, webosint.MediaOCRTopic, webosint.MediaVLTopic}
	for i, want := range wantTopics {
		got, _ := batch[i+1].MetaGet("shadow_output_topic")
		if got != want {
			t.Fatalf("request %d topic = %q want %q", i, got, want)
		}
		structured, err := batch[i+1].AsStructured()
		if err != nil {
			t.Fatal(err)
		}
		request := structured.(map[string]any)
		if request["artifact_id"] != "media-1" || request["source_kind"] != "media" {
			t.Fatalf("request = %#v", request)
		}
		if _, ok := request["shadow_only"]; ok {
			t.Fatalf("production request should not include shadow_only: %#v", request)
		}
	}
}
