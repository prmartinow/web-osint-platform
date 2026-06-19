package mediarequestbuilder

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

const (
	pluginName    = "media_enrichment_request_builder"
	pluginVersion = "0.1.0"

	fieldMode = "mode"
)

func init() {
	spec := service.NewConfigSpec().
		Summary("Build media enrichment requests from projected media observations.").
		Description("In shadow mode this processor appends a shadow wrapper. In production mode it appends request messages for the production media enrichment, OCR, and VL topics.").
		Field(service.NewStringEnumField(fieldMode, "shadow", "production").Default("shadow"))

	constructor := func(conf *service.ParsedConfig, mgr *service.Resources) (service.Processor, error) {
		mode, err := conf.FieldString(fieldMode)
		if err != nil {
			return nil, err
		}
		return &processor{
			mode:   mode,
			built:  mgr.Metrics().NewCounter("media_enrichment_request_builder_built_total"),
			passed: mgr.Metrics().NewCounter("media_enrichment_request_builder_passed_total"),
			failed: mgr.Metrics().NewCounter("media_enrichment_request_builder_failed_total"),
		}, nil
	}
	if err := service.RegisterProcessor(pluginName, spec, constructor); err != nil {
		panic(err)
	}
}

type processor struct {
	mode   string
	built  *service.MetricCounter
	passed *service.MetricCounter
	failed *service.MetricCounter
}

func (p *processor) Process(ctx context.Context, msg *service.Message) (service.MessageBatch, error) {
	structured, err := msg.AsStructured()
	if err != nil {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: parse structured message: %w", pluginName, err)
	}
	root, ok := structured.(map[string]any)
	if !ok {
		incr(p.passed, 1)
		return service.MessageBatch{msg}, nil
	}
	projected, ok := p.projectedMedia(msg, root)
	if !ok {
		incr(p.passed, 1)
		return service.MessageBatch{msg}, nil
	}
	request, ok := webosint.BuildMediaRequest(projected, pluginName, pluginVersion, time.Now, p.mode != "production")
	if !ok {
		incr(p.passed, 1)
		return service.MessageBatch{msg}, nil
	}
	batch := service.MessageBatch{msg}
	if p.mode == "production" {
		for _, topic := range request.TargetTopics {
			out := service.NewMessage(nil)
			copyMetadata(msg, out)
			out.SetStructured(request.Request)
			out.MetaSet("shadow_output_topic", topic)
			out.MetaSet("shadow_output_key", request.TargetKey)
			out.MetaSet("source_kind", "media")
			out.MetaSet("target_key", request.TargetKey)
			if eventID := stringValue(request.Request["event_id"]); eventID != "" {
				out.MetaSet("request_event_id", eventID)
			}
			batch = append(batch, out)
		}
	} else {
		out := service.NewMessage(nil)
		copyMetadata(msg, out)
		out.SetStructured(webosint.MediaRequestShadowEnvelope(pluginName, pluginVersion, request))
		out.MetaSet("shadow_output_topic", webosint.ShadowMediaRequestTopic)
		out.MetaSet("shadow_output_key", request.TargetKey)
		out.MetaSet("source_kind", "media")
		out.MetaSet("target_key", request.TargetKey)
		if eventID := stringValue(request.Request["event_id"]); eventID != "" {
			out.MetaSet("request_event_id", eventID)
		}
		batch = append(batch, out)
	}
	incr(p.built, 1)
	return batch, nil
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

func (p *processor) projectedMedia(msg *service.Message, root map[string]any) (webosint.ProjectedEvent, bool) {
	if p.mode == "production" {
		sourceKind, _ := msg.MetaGet("source_kind")
		if sourceKind != "media" {
			return webosint.ProjectedEvent{}, false
		}
		targetTopic, _ := msg.MetaGet("target_topic")
		targetKey, _ := msg.MetaGet("target_key")
		evidenceID, _ := msg.MetaGet("evidence_id")
		return webosint.ProjectedEvent{
			TargetTopic: targetTopic,
			TargetKey:   targetKey,
			SourceKind:  "media",
			EvidenceID:  evidenceID,
			Observed:    root,
		}, true
	}
	if root["shadow_kind"] != "observed_event_projection" || root["source_kind"] != "media" {
		return webosint.ProjectedEvent{}, false
	}
	observed, ok := root["observed"].(map[string]any)
	if !ok {
		return webosint.ProjectedEvent{}, false
	}
	return webosint.ProjectedEvent{
		TargetTopic: stringValue(root["target_topic"]),
		TargetKey:   stringValue(root["target_key"]),
		SourceKind:  "media",
		EvidenceID:  stringValue(root["evidence_id"]),
		Observed:    observed,
	}, true
}

func stringValue(v any) string {
	switch x := v.(type) {
	case string:
		return x
	case fmt.Stringer:
		return x.String()
	case nil:
		return ""
	default:
		b, err := json.Marshal(x)
		if err != nil {
			return ""
		}
		return string(b)
	}
}

func incr(counter *service.MetricCounter, n int64) {
	if counter != nil {
		counter.Incr(n)
	}
}
