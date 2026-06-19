package dlqenricher

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

func TestDLQEnricherBuildsErrorEnvelope(t *testing.T) {
	msg := service.NewMessage([]byte(`{"bad":true}`))
	msg.MetaSet("kafka_topic", "evidence.capture.events.v1")
	msg.MetaSet("kafka_partition", "0")
	msg.MetaSet("kafka_offset", "42")
	msg.MetaSet("kafka_key", "key-1")
	msg.SetError(errors.New("projection failed"))
	proc := &processor{pipelineName: "capture-shadow-validate"}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if len(batch) != 1 {
		t.Fatalf("batch len = %d", len(batch))
	}
	if topic, _ := batch[0].MetaGet("shadow_output_topic"); topic != webosint.ShadowErrorsTopic {
		t.Fatalf("topic = %q", topic)
	}
	rootRaw, err := batch[0].AsStructured()
	if err != nil {
		t.Fatal(err)
	}
	root := rootRaw.(map[string]any)
	if root["original_offset"] != "42" {
		t.Fatalf("root = %#v", root)
	}
	if !strings.Contains(root["error_message"].(string), "projection failed") {
		t.Fatalf("error_message = %v", root["error_message"])
	}
	if root["payload_sha256"] == "" {
		t.Fatalf("payload hash missing: %#v", root)
	}
}

func TestDLQEnricherCanTargetProductionDLQ(t *testing.T) {
	msg := service.NewMessage([]byte(`{"bad":true}`))
	msg.MetaSet("kafka_topic", "evidence.capture.events.v1")
	msg.MetaSet("kafka_partition", "0")
	msg.MetaSet("kafka_offset", "42")
	msg.SetError(errors.New("production projection failed"))
	proc := &processor{
		pipelineName: "capture-production-observed",
		outputTopic:  "evidence.index.errors.v1",
		errorClass:   "redpanda_connect_production",
	}
	batch, err := proc.Process(context.Background(), msg)
	if err != nil {
		t.Fatal(err)
	}
	if topic, _ := batch[0].MetaGet("shadow_output_topic"); topic != "evidence.index.errors.v1" {
		t.Fatalf("topic = %q", topic)
	}
	rootRaw, err := batch[0].AsStructured()
	if err != nil {
		t.Fatal(err)
	}
	root := rootRaw.(map[string]any)
	if root["error_class"] != "redpanda_connect_production" {
		t.Fatalf("root = %#v", root)
	}
}
