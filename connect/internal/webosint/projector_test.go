package webosint

import (
	"encoding/json"
	"testing"
	"time"
)

func TestProjectObservedForP1Kinds(t *testing.T) {
	event := testCaptureEvent(t)
	projected := ProjectObserved(event)
	byKind := map[string]ProjectedEvent{}
	for _, item := range projected {
		byKind[item.SourceKind] = item
	}

	user := byKind["user_input"]
	if user.TargetTopic != UserInputsObservedTopic {
		t.Fatalf("user target topic = %q", user.TargetTopic)
	}
	if user.TargetKey != "user_input/parity-user-1" || user.EvidenceID != "user_input/parity-user-1" {
		t.Fatalf("user key/evidence = %q/%q", user.TargetKey, user.EvidenceID)
	}
	if got := user.Observed["observation_id"]; got != stableHash("shadow-parity-run", "0", "user_input", "parity-user-1", "0") {
		t.Fatalf("user observation_id = %v", got)
	}
	if got := user.Observed["captured_at"]; got != "2026-06-18T01:02:03Z" {
		t.Fatalf("user captured_at = %v", got)
	}

	web := byKind["web_page"]
	if web.TargetTopic != WebDocsObservedTopic || web.TargetKey != "web_document/parity-web-1" {
		t.Fatalf("web target = %q/%q", web.TargetTopic, web.TargetKey)
	}
	if got := web.Observed["domain"]; got != "example.com" {
		t.Fatalf("web domain = %v", got)
	}

	media := byKind["media"]
	if media.TargetTopic != MediaObservedTopic || media.TargetKey != "parity-media-1" {
		t.Fatalf("media target = %q/%q", media.TargetTopic, media.TargetKey)
	}
	if got := media.Observed["sha256"]; got != "abc123" {
		t.Fatalf("media sha = %v", got)
	}

	search := byKind["search_result"]
	wantSearchID := stableHash("web osint parity", "https://example.com/parity", "0")
	if search.TargetTopic != SearchObservedTopic || search.TargetKey != wantSearchID {
		t.Fatalf("search target = %q/%q want key %q", search.TargetTopic, search.TargetKey, wantSearchID)
	}
	if got := search.Observed["rank"]; got != 1 {
		t.Fatalf("search rank = %v", got)
	}
}

func TestObservedShadowEnvelope(t *testing.T) {
	event := testCaptureEvent(t)
	projected := ProjectObserved(event)[0]
	envelope := ObservedShadowEnvelope("observed_event_projector", "0.1.0", event, projected)
	if envelope["shadow_kind"] != "observed_event_projection" {
		t.Fatalf("shadow_kind = %v", envelope["shadow_kind"])
	}
	if envelope["target_topic"] != projected.TargetTopic || envelope["target_key"] != projected.TargetKey {
		t.Fatalf("target mismatch: %#v", envelope)
	}
	if _, ok := envelope["observed"].(map[string]any); !ok {
		t.Fatalf("observed payload missing: %#v", envelope)
	}
}

func TestBuildMediaRequestFromProjectedMedia(t *testing.T) {
	event := testCaptureEvent(t)
	var media ProjectedEvent
	for _, item := range ProjectObserved(event) {
		if item.SourceKind == "media" {
			media = item
			break
		}
	}
	request, ok := BuildMediaRequest(media, "media_enrichment_request_builder", "0.1.0", func() time.Time {
		return time.Date(2026, 6, 18, 1, 2, 4, 0, time.UTC)
	}, true)
	if !ok {
		t.Fatal("expected media request")
	}
	wantEventID := "media_req_" + stableHash("parity-media-1", "abc123", "/mnt/data/x-research/canaries/connect-shadow/parity.png")[:24]
	if request.Request["event_id"] != wantEventID {
		t.Fatalf("event_id = %v want %s", request.Request["event_id"], wantEventID)
	}
	if request.Request["artifact_role"] != "screenshot_full_page" {
		t.Fatalf("artifact_role = %v", request.Request["artifact_role"])
	}
	if request.Request["media_type"] != "image/png" {
		t.Fatalf("media_type = %v", request.Request["media_type"])
	}
	if request.Request["width"] != 2 || request.Request["height"] != 3 || request.Request["byte_size"] != 67 {
		t.Fatalf("dimensions = %v/%v/%v", request.Request["width"], request.Request["height"], request.Request["byte_size"])
	}
	if request.Request["shadow_only"] != true {
		t.Fatalf("shadow_only = %v", request.Request["shadow_only"])
	}
	envelope := MediaRequestShadowEnvelope("media_enrichment_request_builder", "0.1.0", request)
	if envelope["shadow_kind"] != "media_enrichment_request" {
		t.Fatalf("request envelope = %#v", envelope)
	}
}

func TestBuildMediaRequestProductionPayload(t *testing.T) {
	event := testCaptureEvent(t)
	var media ProjectedEvent
	for _, item := range ProjectObserved(event) {
		if item.SourceKind == "media" {
			media = item
			break
		}
	}
	request, ok := BuildMediaRequest(media, "media_enrichment_request_builder", "0.1.0", func() time.Time {
		return time.Date(2026, 6, 18, 1, 2, 4, 0, time.UTC)
	}, false)
	if !ok {
		t.Fatal("expected media request")
	}
	if _, ok := request.Request["shadow_only"]; ok {
		t.Fatalf("production request should not include shadow_only: %#v", request.Request)
	}
	if _, ok := request.Request["production_topics"]; ok {
		t.Fatalf("production request should not include production_topics: %#v", request.Request)
	}
	if len(request.TargetTopics) != 3 || request.TargetTopics[0] != MediaEnrichmentTopic || request.TargetTopics[1] != MediaOCRTopic || request.TargetTopics[2] != MediaVLTopic {
		t.Fatalf("target topics = %#v", request.TargetTopics)
	}
}

func testCaptureEvent(t *testing.T) CaptureEvent {
	t.Helper()
	raw := []byte(`{
	  "schema_version": "v1",
	  "collector_run_id": "shadow-parity-run",
	  "event_index": 0,
	  "source_project": "canary",
	  "capture_method": "connect_shadow_parity",
	  "captured_at": "2026-06-18T01:02:03Z",
	  "context": {"query": "web osint parity", "engine": "google"},
	  "search_results": [
	    {"rank": 1, "url": "https://example.com/parity", "title": "Parity Result", "snippet": "Search parity snippet."}
	  ],
	  "web_documents": [
	    {"document_id": "parity-web-1", "canonical_url": "https://example.com/parity", "title": "Parity Page", "text": "Web document parity text."}
	  ],
	  "media": [
	    {
	      "media_id": "parity-media-1",
	      "media_kind": "screenshot",
	      "local_path": "/mnt/data/x-research/canaries/connect-shadow/parity.png",
	      "sha256": "abc123",
	      "mime_type": "image/png",
	      "width": 2,
	      "height": 3,
	      "byte_size": 67,
	      "caption": "Parity screenshot"
	    }
	  ],
	  "user_inputs": [
	    {"input_id": "parity-user-1", "input_kind": "research_note", "title": "Parity Note", "text": "User input parity text."}
	  ]
	}`)
	event, err := ParseCaptureEvent(raw)
	if err != nil {
		t.Fatal(err)
	}
	var rawMap map[string]any
	if err := json.Unmarshal(raw, &rawMap); err != nil {
		t.Fatal(err)
	}
	event.Raw = rawMap
	return event
}
