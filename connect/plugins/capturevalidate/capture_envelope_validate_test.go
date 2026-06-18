package capturevalidate

import "testing"

func TestValidateAcceptsUserInputCapture(t *testing.T) {
	index := 0
	event := captureEvent{
		SchemaVersion:  "v1",
		CollectorRunID: "run_canary",
		EventIndex:     &index,
		SourceProject:  "canary",
		CaptureMethod:  "test",
		CapturedAt:     "2026-06-18T00:00:00Z",
		UserInputs:     []map[string]any{{"input_id": "input_1", "text": "hello"}},
	}
	if err := validate(event); err != nil {
		t.Fatalf("expected valid event, got %v", err)
	}
}

func TestValidateRequiresEvidence(t *testing.T) {
	index := 0
	event := captureEvent{
		SchemaVersion:  "v1",
		CollectorRunID: "run_canary",
		EventIndex:     &index,
		SourceProject:  "canary",
		CaptureMethod:  "test",
		CapturedAt:     "2026-06-18T00:00:00Z",
	}
	if err := validate(event); err == nil {
		t.Fatal("expected missing evidence error")
	}
}

func TestValidateRejectsMissingRequiredFields(t *testing.T) {
	event := captureEvent{}
	if err := validate(event); err == nil {
		t.Fatal("expected required field error")
	}
}
