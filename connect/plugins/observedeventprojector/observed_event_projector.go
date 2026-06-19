package observedeventprojector

import (
	"context"
	"fmt"

	"github.com/prmartinow/web-osint-platform/connect/internal/webosint"
	"github.com/redpanda-data/benthos/v4/public/service"
)

const (
	pluginName    = "observed_event_projector"
	pluginVersion = "0.1.0"

	fieldMode             = "mode"
	fieldIncludeValidated = "include_validated"
)

func init() {
	spec := service.NewConfigSpec().
		Summary("Project Web OSINT capture events into observed-event records.").
		Description("In shadow mode this processor emits wrapper records for parity checks. In production mode it emits the observed payloads directly to the production observed topics.").
		Field(service.NewStringEnumField(fieldMode, "shadow", "production").Default("shadow")).
		Field(service.NewBoolField(fieldIncludeValidated).Default(false).Description("Also include the original capture event in the output batch for the validated shadow topic."))

	constructor := func(conf *service.ParsedConfig, mgr *service.Resources) (service.Processor, error) {
		mode, err := conf.FieldString(fieldMode)
		if err != nil {
			return nil, err
		}
		includeValidated, err := conf.FieldBool(fieldIncludeValidated)
		if err != nil {
			return nil, err
		}
		return &processor{
			mode:             mode,
			includeValidated: includeValidated,
			projected:        mgr.Metrics().NewCounter("observed_event_projector_projected_total"),
			failed:           mgr.Metrics().NewCounter("observed_event_projector_failed_total"),
		}, nil
	}
	if err := service.RegisterProcessor(pluginName, spec, constructor); err != nil {
		panic(err)
	}
}

type processor struct {
	mode             string
	includeValidated bool
	projected        *service.MetricCounter
	failed           *service.MetricCounter
}

func (p *processor) Process(ctx context.Context, msg *service.Message) (service.MessageBatch, error) {
	raw, err := msg.AsBytes()
	if err != nil {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: read message bytes: %w", pluginName, err)
	}
	event, err := webosint.ParseCaptureEvent(raw)
	if err != nil {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: parse capture event: %w", pluginName, err)
	}
	projected := webosint.ProjectObserved(event)
	if len(projected) == 0 {
		incr(p.failed, 1)
		return nil, fmt.Errorf("%s: capture event produced no observed records", pluginName)
	}
	batch := make(service.MessageBatch, 0, len(projected)+1)
	if p.includeValidated {
		validated := msg.Copy()
		validated.MetaSet("shadow_output_topic", webosint.ShadowValidatedTopic)
		if key, ok := msg.MetaGet("kafka_key"); ok {
			validated.MetaSet("shadow_output_key", key)
		}
		batch = append(batch, validated)
	}
	for _, item := range projected {
		out := service.NewMessage(nil)
		copyMetadata(msg, out)
		if p.mode == "production" {
			out.SetStructured(item.Observed)
			out.MetaSet("shadow_output_topic", item.TargetTopic)
		} else {
			out.SetStructured(webosint.ObservedShadowEnvelope(pluginName, pluginVersion, event, item))
			out.MetaSet("shadow_output_topic", webosint.ShadowObservedTopic)
		}
		out.MetaSet("shadow_output_key", item.TargetKey)
		out.MetaSet("target_topic", item.TargetTopic)
		out.MetaSet("target_key", item.TargetKey)
		out.MetaSet("source_kind", item.SourceKind)
		out.MetaSet("evidence_id", item.EvidenceID)
		batch = append(batch, out)
	}
	incr(p.projected, int64(len(projected)))
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

func incr(counter *service.MetricCounter, n int64) {
	if counter != nil {
		counter.Incr(n)
	}
}
