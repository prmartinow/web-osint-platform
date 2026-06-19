package dlqenricher

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

const (
	pluginName    = "dlq_error_enricher"
	pluginVersion = "0.1.0"

	fieldPipelineName = "pipeline_name"
	fieldOutputTopic  = "output_topic"
	fieldErrorClass   = "error_class"
)

func init() {
	spec := service.NewConfigSpec().
		Summary("Enrich failed Web OSINT Connect messages for DLQ topics.").
		Description("This processor replaces a failed message with a deterministic DLQ envelope that includes source topic metadata, payload hash, plugin version, and error details.").
		Field(service.NewStringField(fieldPipelineName).Default("web-osint-connect-shadow")).
		Field(service.NewStringField(fieldOutputTopic).Default(webosint.ShadowErrorsTopic)).
		Field(service.NewStringField(fieldErrorClass).Default("redpanda_connect_shadow"))

	constructor := func(conf *service.ParsedConfig, mgr *service.Resources) (service.Processor, error) {
		pipelineName, err := conf.FieldString(fieldPipelineName)
		if err != nil {
			return nil, err
		}
		outputTopic, err := conf.FieldString(fieldOutputTopic)
		if err != nil {
			return nil, err
		}
		errorClass, err := conf.FieldString(fieldErrorClass)
		if err != nil {
			return nil, err
		}
		return &processor{
			pipelineName: pipelineName,
			outputTopic:  outputTopic,
			errorClass:   errorClass,
			enriched:     mgr.Metrics().NewCounter("dlq_error_enricher_enriched_total"),
		}, nil
	}
	if err := service.RegisterProcessor(pluginName, spec, constructor); err != nil {
		panic(err)
	}
}

type processor struct {
	pipelineName string
	outputTopic  string
	errorClass   string
	enriched     *service.MetricCounter
}

func (p *processor) Process(ctx context.Context, msg *service.Message) (service.MessageBatch, error) {
	raw, err := msg.AsBytes()
	if err != nil {
		raw = []byte(fmt.Sprintf("<failed to read message bytes: %v>", err))
	}
	errMsg := ""
	if msgErr := msg.GetError(); msgErr != nil {
		errMsg = msgErr.Error()
	}
	if errMsg == "" {
		errMsg = meta(msg, "error")
	}
	payload := map[string]any{
		"schema_version":      "v1",
		"error_class":         p.errorClassValue(),
		"error_message":       errMsg,
		"pipeline_name":       p.pipelineName,
		"plugin_name":         pluginName,
		"plugin_version":      pluginVersion,
		"original_topic":      meta(msg, "kafka_topic"),
		"original_partition":  meta(msg, "kafka_partition"),
		"original_offset":     meta(msg, "kafka_offset"),
		"original_key":        meta(msg, "kafka_key"),
		"trace_id":            firstMeta(msg, "trace_id", "request_id", "correlation_id"),
		"payload_sha256":      sha256Hex(raw),
		"raw":                 string(raw),
		"created_at":          time.Now().UTC().Format(time.RFC3339Nano),
		"source_kind_router":  meta(msg, "source_kind_router_kinds"),
		"source_kind_counts":  meta(msg, "source_kind_router_counts"),
		"failed_output_topic": meta(msg, "shadow_output_topic"),
		"failed_output_key":   meta(msg, "shadow_output_key"),
		"failed_target_topic": meta(msg, "target_topic"),
		"failed_target_key":   meta(msg, "target_key"),
		"failed_source_kind":  meta(msg, "source_kind"),
		"failed_evidence_id":  meta(msg, "evidence_id"),
	}
	out := service.NewMessage(nil)
	copyMetadata(msg, out)
	out.SetStructured(payload)
	out.MetaSet("shadow_output_topic", p.outputTopicValue())
	out.MetaSet("shadow_output_key", fmt.Sprintf("%s/%s/%s", meta(msg, "kafka_topic"), meta(msg, "kafka_partition"), meta(msg, "kafka_offset")))
	incr(p.enriched, 1)
	return service.MessageBatch{out}, nil
}

func (p *processor) Close(ctx context.Context) error {
	return nil
}

func copyMetadata(src, dst *service.Message) {
	_ = src.MetaWalk(func(key, value string) error {
		dst.MetaSet(key, value)
		return nil
	})
}

func meta(msg *service.Message, key string) string {
	value, _ := msg.MetaGet(key)
	return value
}

func firstMeta(msg *service.Message, keys ...string) string {
	for _, key := range keys {
		if value, ok := msg.MetaGet(key); ok && value != "" {
			return value
		}
	}
	return ""
}

func sha256Hex(raw []byte) string {
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func (p *processor) outputTopicValue() string {
	if p.outputTopic != "" {
		return p.outputTopic
	}
	return webosint.ShadowErrorsTopic
}

func (p *processor) errorClassValue() string {
	if p.errorClass != "" {
		return p.errorClass
	}
	return "redpanda_connect_shadow"
}

func incr(counter *service.MetricCounter, n int64) {
	if counter != nil {
		counter.Incr(n)
	}
}
