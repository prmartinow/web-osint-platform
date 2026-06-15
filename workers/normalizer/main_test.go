package main

import "testing"

func TestDeterministicAnnotationsForLeaderboardPage(t *testing.T) {
	row := chEvidenceRow{
		EventID:      "evt-1",
		SourceKind:   "web_page",
		EvidenceID:   "capture/run:1",
		CanonicalURL: "https://example.ai/leaderboard",
		Domain:       "example.ai",
		Title:        "Model leaderboard",
		Text:         "Rank Model Score Benchmark",
		Topics:       []string{"AI Benchmarks"},
		Entities:     []string{"Model X"},
		Links:        []string{"https://example.ai/model-x"},
		RawJSON:      `{"title":"Model leaderboard"}`,
	}

	annotations := deterministicAnnotations(row, map[string]any{"quality": map[string]any{}})
	labels := annotationLabels(annotations)

	assertLabel(t, labels, "source.x.post", false)
	assertLabel(t, labels, "source.web.page", true)
	assertLabel(t, labels, "form.leaderboard", true)
	assertLabel(t, labels, "modality.table", true)
	assertLabel(t, labels, "topic.ai_benchmarks", true)
	assertLabel(t, labels, "entity.mentioned", true)
	assertLabel(t, labels, "quality.direct_web_capture", true)
	assertLabel(t, labels, "action.compare", true)
	assertLabel(t, labels, "action.collect_more", true)
}

func TestDeterministicAnnotationsForXPost(t *testing.T) {
	row := chEvidenceRow{
		EventID:      "evt-2",
		SourceKind:   "x_post",
		EvidenceID:   "1234567890",
		CanonicalURL: "https://x.com/example/status/1234567890",
		AuthorHandle: "example",
		Text:         "We are launching Model X today with a new model card.",
		Topics:       []string{"Model Releases"},
		RawJSON:      `{"post_id":"1234567890"}`,
	}

	annotations := deterministicAnnotations(row, map[string]any{"quality": map[string]any{}})
	labels := annotationLabels(annotations)

	assertLabel(t, labels, "source.x.post", true)
	assertLabel(t, labels, "form.social_post", true)
	assertLabel(t, labels, "modality.text", true)
	assertLabel(t, labels, "topic.model_releases", true)
	assertLabel(t, labels, "action.verify", true)
}

func TestSlugLabel(t *testing.T) {
	got := slugLabel("MCP Security Risks / Agentic Browsing")
	want := "mcp_security_risks_agentic_browsing"
	if got != want {
		t.Fatalf("slugLabel() = %q, want %q", got, want)
	}
}

func annotationLabels(rows []chSemanticAnnotationRow) map[string]bool {
	out := map[string]bool{}
	for _, row := range rows {
		out[row.LabelID] = true
	}
	return out
}

func assertLabel(t *testing.T, labels map[string]bool, label string, want bool) {
	t.Helper()
	if labels[label] != want {
		t.Fatalf("label %q present=%v, want %v; labels=%v", label, labels[label], want, labels)
	}
}
