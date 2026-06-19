package observedeventprojector

import (
	"context"
	"testing"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

func TestProjectorIncludesValidatedAndObservedMessages(t *testing.T) {
	msg := service.NewMessage([]byte(`{
	  "schema_version":"v1",
	  "collector_run_id":"run",
	  "event_index":0,
	  "source_project":"canary",
	  "capture_method":"test",
	  "captured_at":"2026-06-18T00:00:00Z",
	  "user_inputs":[{"input_id":"u1","text":"hello"}]
	}`))
	msg.MetaSet("kafka_key", "capture-key")
	proc := &processor{includeValidated: true}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch) != 2 {
		t.Fatalf("batch len = %d", len(batch))
	}
	if topic, _ := batch[0].MetaGet("shadow_output_topic"); topic != webosint.ShadowValidatedTopic {
		t.Fatalf("validated topic = %q", topic)
	}
	if topic, _ := batch[1].MetaGet("shadow_output_topic"); topic != webosint.ShadowObservedTopic {
		t.Fatalf("observed topic = %q", topic)
	}
	structured, err := batch[1].AsStructured()
	if err != nil {
		t.Fatal(err)
	}
	root := structured.(map[string]any)
	if root["source_kind"] != "user_input" || root["target_key"] != "user_input/u1" {
		t.Fatalf("projection root = %#v", root)
	}
}

func TestProjectorProductionModeEmitsObservedPayload(t *testing.T) {
	msg := service.NewMessage([]byte(`{
	  "schema_version":"v1",
	  "collector_run_id":"run",
	  "event_index":0,
	  "source_project":"canary",
	  "capture_method":"test",
	  "captured_at":"2026-06-18T00:00:00Z",
	  "user_inputs":[{"input_id":"u1","text":"hello"}]
	}`))
	proc := &processor{mode: "production"}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch) != 1 {
		t.Fatalf("batch len = %d", len(batch))
	}
	if topic, _ := batch[0].MetaGet("shadow_output_topic"); topic != webosint.UserInputsObservedTopic {
		t.Fatalf("observed topic = %q", topic)
	}
	if key, _ := batch[0].MetaGet("shadow_output_key"); key != "user_input/u1" {
		t.Fatalf("observed key = %q", key)
	}
	structured, err := batch[0].AsStructured()
	if err != nil {
		t.Fatal(err)
	}
	root := structured.(map[string]any)
	if _, ok := root["shadow_kind"]; ok {
		t.Fatalf("production payload should not be wrapped: %#v", root)
	}
	if root["evidence_id"] != "user_input/u1" || root["text"] != "hello" {
		t.Fatalf("production payload = %#v", root)
	}
}
