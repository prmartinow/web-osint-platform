package sourcekindrouter

import (
	"context"
	"testing"

	"github.com/redpanda-data/benthos/v4/public/service"
)

func TestRouterSetsSourceKindMetadata(t *testing.T) {
	msg := service.NewMessage([]byte(`{
	  "schema_version":"v1",
	  "collector_run_id":"run",
	  "event_index":0,
	  "source_project":"canary",
	  "capture_method":"test",
	  "captured_at":"2026-06-18T00:00:00Z",
	  "media":[{"media_id":"m1"}],
	  "user_inputs":[{"input_id":"u1","text":"hello"}]
	}`))
	proc := &processor{}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch) != 1 || batch[0] != msg {
		t.Fatalf("batch = %#v", batch)
	}
	if got, _ := msg.MetaGet("source_kind_router_kinds"); got != "media,user_input" {
		t.Fatalf("source kinds = %q", got)
	}
	if got, _ := msg.MetaGet("source_kind_router_total"); got != "2" {
		t.Fatalf("total = %q", got)
	}
}
