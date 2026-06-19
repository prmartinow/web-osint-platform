package webosint

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"mime"
	"net/url"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	PostsObservedTopic      = "evidence.posts.observed.v1"
	AccountsObservedTopic   = "evidence.accounts.observed.v1"
	MediaObservedTopic      = "evidence.media.observed.v1"
	SearchObservedTopic     = "evidence.search.results.v1"
	WebDocsObservedTopic    = "evidence.web.documents.observed.v1"
	UserInputsObservedTopic = "evidence.user.inputs.observed.v1"

	ShadowValidatedTopic    = "evidence.capture.shadow.validated.v1"
	ShadowObservedTopic     = "evidence.capture.shadow.observed.v1"
	ShadowMediaRequestTopic = "osint.media.enrichment.shadow.requested.v1"
	ShadowErrorsTopic       = "evidence.capture.shadow.errors.v1"

	MediaEnrichmentTopic = "osint.media.enrichment.requested.v1"
	MediaOCRTopic        = "osint.media.ocr.requested.v1"
	MediaVLTopic         = "osint.media.vl_embedding.requested.v1"
)

const (
	DefaultMediaMaxImageBytes  = 25 * 1024 * 1024
	DefaultMediaMaxImagePixels = 40_000_000
	DefaultMediaVLMaxSide      = 1600
)

var statusURLPattern = regexp.MustCompile(`(?i)(?:x|twitter)\.com/([^/?#]+)/status/([0-9]+)`)

type CaptureEvent struct {
	SchemaVersion  string           `json:"schema_version"`
	CollectorRunID string           `json:"collector_run_id"`
	EventIndex     int              `json:"event_index"`
	SourceProject  string           `json:"source_project"`
	CaptureMethod  string           `json:"capture_method"`
	CapturedAt     string           `json:"captured_at"`
	PageURL        string           `json:"page_url"`
	PageTitle      string           `json:"page_title"`
	Context        map[string]any   `json:"context"`
	Posts          []map[string]any `json:"posts"`
	Accounts       []map[string]any `json:"accounts"`
	Media          []map[string]any `json:"media"`
	WebDocuments   []map[string]any `json:"web_documents"`
	UserInputs     []map[string]any `json:"user_inputs"`
	Links          []any            `json:"links"`
	Quality        map[string]any   `json:"quality"`
	Raw            map[string]any   `json:"-"`
}

type ProjectedEvent struct {
	TargetTopic string
	TargetKey   string
	SourceKind  string
	EvidenceID  string
	Observed    map[string]any
}

type MediaRequest struct {
	TargetTopics []string
	TargetKey    string
	Request      map[string]any
}

func ParseCaptureEvent(raw []byte) (CaptureEvent, error) {
	var root map[string]any
	if err := json.Unmarshal(raw, &root); err != nil {
		return CaptureEvent{}, err
	}
	var ev CaptureEvent
	if err := json.Unmarshal(raw, &ev); err != nil {
		return CaptureEvent{}, err
	}
	ev.Raw = root
	if ev.SchemaVersion == "" {
		ev.SchemaVersion = "v1"
	}
	if ev.CapturedAt == "" {
		ev.CapturedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	return ev, nil
}

func SourceKindCounts(ev CaptureEvent) map[string]int {
	counts := map[string]int{}
	add := func(kind string, n int) {
		if n > 0 {
			counts[kind] += n
		}
	}
	add("x_post", len(ev.Posts))
	add("x_account", len(ev.Accounts))
	add("media", len(ev.Media))
	add("search_result", len(SearchResultsFrom(ev.Raw, ev.Context)))
	add("web_page", len(WebDocumentsFrom(ev.Raw, ev.Context, ev.WebDocuments)))
	add("user_input", len(UserInputsFrom(ev.Raw, ev.Context, ev.UserInputs)))
	if len(counts) == 0 {
		add(SourceKindForCapture(ev), 1)
	}
	return counts
}

func SourceKinds(ev CaptureEvent) []string {
	counts := SourceKindCounts(ev)
	kinds := make([]string, 0, len(counts))
	for _, kind := range []string{"x_post", "x_account", "media", "search_result", "web_page", "user_input", "capture", "x_page", "google_search_page"} {
		if counts[kind] > 0 {
			kinds = append(kinds, kind)
		}
	}
	return kinds
}

func ProjectObserved(ev CaptureEvent) []ProjectedEvent {
	var out []ProjectedEvent
	for i, post := range ev.Posts {
		out = append(out, projectPost(ev, i, post))
	}
	for i, account := range ev.Accounts {
		out = append(out, projectAccount(ev, i, account))
	}
	for i, media := range ev.Media {
		out = append(out, projectMedia(ev, i, media))
	}
	for i, result := range SearchResultsFrom(ev.Raw, ev.Context) {
		out = append(out, projectSearchResult(ev, i, result))
	}
	for i, document := range WebDocumentsFrom(ev.Raw, ev.Context, ev.WebDocuments) {
		out = append(out, projectWebDocument(ev, i, document))
	}
	for i, input := range UserInputsFrom(ev.Raw, ev.Context, ev.UserInputs) {
		out = append(out, projectUserInput(ev, i, input))
	}
	return out
}

func ObservedShadowEnvelope(projectorName, projectorVersion string, ev CaptureEvent, projected ProjectedEvent) map[string]any {
	return map[string]any{
		"schema_version":    "v1",
		"shadow_kind":       "observed_event_projection",
		"projector_name":    projectorName,
		"projector_version": projectorVersion,
		"collector_run_id":  ev.CollectorRunID,
		"event_index":       ev.EventIndex,
		"target_topic":      projected.TargetTopic,
		"target_key":        projected.TargetKey,
		"source_kind":       projected.SourceKind,
		"evidence_id":       projected.EvidenceID,
		"observed":          projected.Observed,
	}
}

func BuildMediaRequest(
	projected ProjectedEvent,
	producerName string,
	producerVersion string,
	now func() time.Time,
	shadowOnly bool,
) (MediaRequest, bool) {
	if projected.SourceKind != "media" || projected.Observed == nil {
		return MediaRequest{}, false
	}
	observed := projected.Observed
	raw := firstMap(observed, "raw")
	nested := firstMap(raw, "raw")
	path := firstString(raw, "local_path", "storage_path", "path", "artifact_path")
	if path == "" {
		path = firstString(nested, "local_path", "storage_path", "path", "artifact_path")
	}
	if path == "" {
		path = firstString(observed, "local_path")
	}
	evidenceID := projected.EvidenceID
	if evidenceID == "" {
		evidenceID = firstString(observed, "media_id")
	}
	sha := firstString(raw, "sha256")
	if sha == "" {
		sha = firstString(nested, "sha256")
	}
	if sha == "" {
		sha = firstString(observed, "sha256")
	}
	if sha == "" {
		sha = stableHash(evidenceID, path)[:32]
	}
	artifactID := firstString(raw, "media_id")
	if artifactID == "" {
		artifactID = firstString(nested, "media_id")
	}
	if artifactID == "" {
		artifactID = firstString(observed, "media_id")
	}
	if artifactID == "" {
		artifactID = evidenceID
	}
	role := firstString(observed, "media_kind")
	if role == "" {
		role = firstString(raw, "media_kind", "kind", "type")
	}
	if role == "" {
		role = firstString(nested, "media_kind", "kind", "type")
	}
	if role == "" {
		role = "image"
	}
	mimeType := firstString(raw, "mime_type")
	if mimeType == "" {
		mimeType = firstString(nested, "mime_type")
	}
	if mimeType == "" && path != "" {
		mimeType = mime.TypeByExtension(strings.ToLower(filepath.Ext(path)))
	}
	if mimeType == "" {
		mimeType = "image/png"
	}
	requestedAt := time.Now().UTC()
	if now != nil {
		requestedAt = now().UTC()
	}
	request := map[string]any{
		"schema_version":   "v1",
		"event_id":         "media_req_" + stableHash(evidenceID, sha, path)[:24],
		"trace_id":         "media_req_" + stableHash(evidenceID, sha, path)[:24],
		"evidence_id":      evidenceID,
		"artifact_id":      artifactID,
		"artifact_sha256":  sha,
		"source_kind":      "media",
		"source_project":   firstString(observed, "source_project"),
		"capture_method":   firstString(observed, "capture_method"),
		"collector_run_id": firstString(observed, "collector_run_id"),
		"artifact_role":    artifactRole(role),
		"media_type":       mimeType,
		"storage_path":     path,
		"source_uri":       firstString(observed, "url"),
		"caption":          firstString(observed, "caption"),
		"topics":           asStringSlice(observed["topics"]),
		"width":            firstInt(firstNonNil(observed, "width"), firstNonNil(raw, "width"), firstNonNil(nested, "width")),
		"height":           firstInt(firstNonNil(observed, "height"), firstNonNil(raw, "height"), firstNonNil(nested, "height")),
		"byte_size":        firstInt(firstNonNil(observed, "byte_size"), firstNonNil(observed, "bytes"), firstNonNil(raw, "byte_size"), firstNonNil(raw, "bytes"), firstNonNil(nested, "byte_size"), firstNonNil(nested, "bytes")),
		"producer_name":    producerName,
		"producer_version": producerVersion,
		"params_hash":      MediaParamsHash(DefaultMediaMaxImageBytes, DefaultMediaMaxImagePixels, DefaultMediaVLMaxSide),
		"requested_at":     requestedAt.Format(time.RFC3339Nano),
	}
	if shadowOnly {
		request["shadow_only"] = true
		request["production_topics"] = []string{MediaEnrichmentTopic, MediaOCRTopic, MediaVLTopic}
	}
	return MediaRequest{
		TargetTopics: []string{MediaEnrichmentTopic, MediaOCRTopic, MediaVLTopic},
		TargetKey:    artifactID,
		Request:      request,
	}, true
}

func MediaRequestShadowEnvelope(builderName, builderVersion string, request MediaRequest) map[string]any {
	return map[string]any{
		"schema_version":   "v1",
		"shadow_kind":      "media_enrichment_request",
		"builder_name":     builderName,
		"builder_version":  builderVersion,
		"target_topics":    request.TargetTopics,
		"target_key":       request.TargetKey,
		"shadow_only":      true,
		"request":          request.Request,
		"request_event_id": request.Request["event_id"],
	}
}

func MediaParamsHash(maxBytes, maxPixels, vlMaxSide int) string {
	return stableHash(
		"media-v1",
		fmt.Sprintf("max_bytes=%d", maxBytes),
		fmt.Sprintf("max_pixels=%d", maxPixels),
		fmt.Sprintf("vl_max_side=%d", vlMaxSide),
	)[:16]
}

func projectPost(ev CaptureEvent, idx int, post map[string]any) ProjectedEvent {
	postID := firstString(post, "post_id", "id", "tweet_id", "status_id")
	canonicalURL := firstString(post, "canonical_url", "url", "href")
	if postID == "" {
		if handle, id := postIDFromURL(canonicalURL); id != "" {
			postID = id
			if firstString(post, "author_handle", "handle", "screen_name", "username") == "" {
				post["author_handle"] = handle
			}
		}
	}
	if canonicalURL == "" && postID != "" {
		handle := cleanHandle(firstString(post, "author_handle", "handle", "screen_name", "username"))
		if handle != "" {
			canonicalURL = fmt.Sprintf("https://x.com/%s/status/%s", handle, postID)
		}
	}
	if postID == "" {
		postID = stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "post", strconv.Itoa(idx), canonicalURL, firstString(post, "text", "full_text", "content", "body"))[:16]
	}
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "post", postID, strconv.Itoa(idx))
	authorHandle := cleanHandle(firstString(post, "author_handle", "handle", "screen_name", "username"))
	links := linksFromPost(post)
	observed := map[string]any{
		"schema_version":   "v1",
		"observation_id":   observationID,
		"collector_run_id": ev.CollectorRunID,
		"source_project":   ev.SourceProject,
		"capture_method":   ev.CaptureMethod,
		"captured_at":      normalizeTimeString(ev.CapturedAt),
		"post_id":          postID,
		"canonical_url":    canonicalURL,
		"raw_urls":         appendUnique(links, canonicalURL),
		"author_handle":    authorHandle,
		"author_name":      firstString(post, "author_name", "name", "display_name"),
		"posted_at":        optionalTime(firstString(post, "posted_at", "created_at", "time", "timestamp")),
		"text":             firstString(post, "text", "full_text", "content", "body"),
		"lang":             firstString(post, "lang", "language"),
		"links":            links,
		"media_ids":        asStringSlice(firstNonNil(post, "media_ids", "media")),
		"topics":           asStringSlice(post["topics"]),
		"entities":         entitiesFrom(post["entities"]),
		"quality":          firstMap(post, "quality"),
		"raw":              post,
	}
	if post["vectors"] != nil {
		observed["vectors"] = post["vectors"]
	}
	return ProjectedEvent{TargetTopic: PostsObservedTopic, TargetKey: postID, SourceKind: "x_post", EvidenceID: postID, Observed: observed}
}

func projectAccount(ev CaptureEvent, idx int, account map[string]any) ProjectedEvent {
	handle := cleanHandle(firstString(account, "handle", "author_handle", "screen_name", "username"))
	if handle == "" {
		handle = stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "account", strconv.Itoa(idx), mustJSON(account))[:16]
	}
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "account", handle, strconv.Itoa(idx))
	observed := map[string]any{
		"schema_version":    "v1",
		"observation_id":    observationID,
		"collector_run_id":  ev.CollectorRunID,
		"source_project":    ev.SourceProject,
		"capture_method":    ev.CaptureMethod,
		"captured_at":       normalizeTimeString(ev.CapturedAt),
		"normalized_handle": handle,
		"profile_url":       firstString(account, "profile_url", "url"),
		"display_name":      firstString(account, "display_name", "name", "author_name"),
		"bio":               firstString(account, "bio", "description", "text"),
		"website_urls":      linksFromPost(account),
		"topics":            asStringSlice(account["topics"]),
		"entities":          entitiesFrom(account["entities"]),
		"raw":               account,
	}
	if account["vectors"] != nil {
		observed["vectors"] = account["vectors"]
	}
	return ProjectedEvent{TargetTopic: AccountsObservedTopic, TargetKey: handle, SourceKind: "x_account", EvidenceID: handle, Observed: observed}
}

func projectMedia(ev CaptureEvent, idx int, media map[string]any) ProjectedEvent {
	mediaID := firstString(media, "media_id", "id", "sha256", "url", "local_path")
	if mediaID == "" {
		mediaID = stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "media", strconv.Itoa(idx), mustJSON(media))[:32]
	}
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "media", mediaID, strconv.Itoa(idx))
	observed := map[string]any{
		"schema_version":   "v1",
		"observation_id":   observationID,
		"collector_run_id": ev.CollectorRunID,
		"source_project":   ev.SourceProject,
		"capture_method":   ev.CaptureMethod,
		"captured_at":      normalizeTimeString(ev.CapturedAt),
		"media_id":         mediaID,
		"media_kind":       firstString(media, "media_kind", "type", "kind"),
		"url":              firstString(media, "url", "src"),
		"local_path":       firstString(media, "local_path", "path"),
		"sha256":           firstString(media, "sha256"),
		"ocr_text":         firstString(media, "ocr_text"),
		"caption":          firstString(media, "caption", "alt_text", "description"),
		"topics":           asStringSlice(media["topics"]),
		"entities":         entitiesFrom(media["entities"]),
		"raw":              media,
	}
	if media["vectors"] != nil {
		observed["vectors"] = media["vectors"]
	}
	return ProjectedEvent{TargetTopic: MediaObservedTopic, TargetKey: mediaID, SourceKind: "media", EvidenceID: mediaID, Observed: observed}
}

func projectSearchResult(ev CaptureEvent, idx int, result map[string]any) ProjectedEvent {
	resultURL := firstString(result, "url", "href", "link")
	query := firstString(result, "query")
	if query == "" && ev.Context != nil {
		query = stringFromAny(ev.Context["query"])
	}
	engine := firstString(result, "engine", "source")
	if engine == "" && ev.Context != nil {
		engine = stringFromAny(ev.Context["engine"])
	}
	if engine == "" {
		engine = "google"
	}
	id := stableHash(query, resultURL, strconv.Itoa(idx))
	observed := map[string]any{
		"schema_version":    "v1",
		"collector_run_id":  ev.CollectorRunID,
		"source_project":    ev.SourceProject,
		"capture_method":    ev.CaptureMethod,
		"searched_at":       normalizeTimeString(ev.CapturedAt),
		"engine":            engine,
		"query":             query,
		"rank":              rankFrom(result, idx),
		"url":               resultURL,
		"canonical_post_id": postIDOnlyFromURL(resultURL),
		"title":             firstString(result, "title"),
		"snippet":           firstString(result, "snippet", "description", "text"),
		"challenge":         asBool(result["challenge"]) || challengeFlag(ev.Quality),
		"raw":               result,
	}
	return ProjectedEvent{TargetTopic: SearchObservedTopic, TargetKey: id, SourceKind: "search_result", EvidenceID: id, Observed: observed}
}

func projectWebDocument(ev CaptureEvent, idx int, document map[string]any) ProjectedEvent {
	canonicalURL := firstString(document, "canonical_url", "url", "source_url", "page_url", "href", "link")
	documentID := firstString(document, "document_id", "id")
	if documentID == "" {
		documentID = stableHash(canonicalURL, firstString(document, "text_hash", "sha256"), firstString(document, "title"), firstString(document, "text", "content", "body", "markdown", "summary"), strconv.Itoa(idx))[:24]
	}
	evidenceID := "web_document/" + documentID
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "web_document", documentID, strconv.Itoa(idx))
	capturedAt := firstString(document, "captured_at", "retrieved_at", "extracted_at")
	if capturedAt == "" {
		capturedAt = ev.CapturedAt
	}
	domain := firstString(document, "domain", "host")
	if domain == "" {
		domain = hostOf(canonicalURL)
	}
	observed := map[string]any{
		"schema_version":   "v1",
		"observation_id":   observationID,
		"collector_run_id": ev.CollectorRunID,
		"source_project":   ev.SourceProject,
		"capture_method":   ev.CaptureMethod,
		"captured_at":      normalizeTimeString(capturedAt),
		"document_id":      documentID,
		"evidence_id":      evidenceID,
		"canonical_url":    canonicalURL,
		"domain":           domain,
		"title":            firstString(document, "title", "page_title", "headline"),
		"text":             firstString(document, "text", "content", "body", "markdown", "summary", "extracted_text"),
		"content_type":     firstString(document, "content_type", "mime_type"),
		"document_kind":    firstString(document, "document_kind", "kind", "content_form"),
		"published_at":     optionalTime(firstString(document, "published_at", "posted_at", "created_at", "date")),
		"links":            linksFromPost(document),
		"media_ids":        asStringSlice(firstNonNil(document, "media_ids", "media")),
		"topics":           asStringSlice(document["topics"]),
		"entities":         entitiesFrom(document["entities"]),
		"artifact_paths":   asStringSlice(firstNonNil(document, "artifact_paths", "local_paths", "paths")),
		"tables":           firstNonNil(document, "tables", "table_snapshots"),
		"quality":          firstMap(document, "quality"),
		"raw":              document,
	}
	if document["vectors"] != nil {
		observed["vectors"] = document["vectors"]
	}
	return ProjectedEvent{TargetTopic: WebDocsObservedTopic, TargetKey: evidenceID, SourceKind: "web_page", EvidenceID: evidenceID, Observed: observed}
}

func projectUserInput(ev CaptureEvent, idx int, input map[string]any) ProjectedEvent {
	inputID := firstString(input, "input_id", "note_id", "id")
	text := firstString(input, "text", "content", "note", "body", "markdown", "summary")
	if inputID == "" {
		inputID = stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "user_input", text, strconv.Itoa(idx))[:24]
	}
	evidenceID := "user_input/" + inputID
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "user_input", inputID, strconv.Itoa(idx))
	capturedAt := firstString(input, "captured_at", "created_at", "observed_at")
	if capturedAt == "" {
		capturedAt = ev.CapturedAt
	}
	observed := map[string]any{
		"schema_version":   "v1",
		"observation_id":   observationID,
		"collector_run_id": ev.CollectorRunID,
		"source_project":   ev.SourceProject,
		"capture_method":   ev.CaptureMethod,
		"captured_at":      normalizeTimeString(capturedAt),
		"input_id":         inputID,
		"evidence_id":      evidenceID,
		"input_kind":       firstString(input, "input_kind", "kind", "type"),
		"author":           firstString(input, "author", "user", "created_by"),
		"title":            firstString(input, "title", "subject", "heading"),
		"text":             text,
		"links":            linksFromPost(input),
		"topics":           asStringSlice(input["topics"]),
		"entities":         entitiesFrom(input["entities"]),
		"attachments":      firstNonNil(input, "attachments", "files"),
		"context":          firstMap(input, "context"),
		"quality":          firstMap(input, "quality"),
		"raw":              input,
	}
	if input["vectors"] != nil {
		observed["vectors"] = input["vectors"]
	}
	return ProjectedEvent{TargetTopic: UserInputsObservedTopic, TargetKey: evidenceID, SourceKind: "user_input", EvidenceID: evidenceID, Observed: observed}
}

func SearchResultsFrom(raw map[string]any, context map[string]any) []map[string]any {
	for _, source := range []map[string]any{raw, context} {
		for _, key := range []string{"search_results", "results"} {
			if list, ok := source[key].([]any); ok {
				var out []map[string]any
				for _, item := range list {
					if m, ok := item.(map[string]any); ok {
						out = append(out, m)
					}
				}
				if len(out) > 0 {
					return out
				}
			}
		}
	}
	return nil
}

func WebDocumentsFrom(raw map[string]any, context map[string]any, direct []map[string]any) []map[string]any {
	if len(direct) > 0 {
		return direct
	}
	return firstMapList([]map[string]any{raw, context}, "web_documents", "documents", "pages", "web_pages", "articles")
}

func UserInputsFrom(raw map[string]any, context map[string]any, direct []map[string]any) []map[string]any {
	if len(direct) > 0 {
		return direct
	}
	return firstMapList([]map[string]any{raw, context}, "user_inputs", "user_notes", "notes", "research_notes", "manual_inputs")
}

func SourceKindForCapture(ev CaptureEvent) string {
	if ev.PageURL == "" {
		return "capture"
	}
	h := hostOf(ev.PageURL)
	switch {
	case strings.Contains(h, "x.com") || strings.Contains(h, "twitter.com"):
		return "x_page"
	case strings.Contains(h, "google."):
		return "google_search_page"
	default:
		return "web_page"
	}
}

func firstMapList(sources []map[string]any, keys ...string) []map[string]any {
	for _, source := range sources {
		if source == nil {
			continue
		}
		for _, key := range keys {
			if list, ok := source[key].([]any); ok {
				var out []map[string]any
				for _, item := range list {
					if m, ok := item.(map[string]any); ok {
						out = append(out, m)
					}
				}
				if len(out) > 0 {
					return out
				}
			}
		}
	}
	return nil
}

func firstString(m map[string]any, keys ...string) string {
	if m == nil {
		return ""
	}
	for _, key := range keys {
		if s := stringFromAny(m[key]); s != "" {
			return s
		}
	}
	return ""
}

func stringFromAny(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return strings.TrimSpace(x)
	case fmt.Stringer:
		return strings.TrimSpace(x.String())
	case float64:
		if math.Trunc(x) == x {
			return strconv.FormatInt(int64(x), 10)
		}
		return strconv.FormatFloat(x, 'f', -1, 64)
	case int:
		return strconv.Itoa(x)
	case int64:
		return strconv.FormatInt(x, 10)
	case json.Number:
		return x.String()
	case bool:
		return strconv.FormatBool(x)
	default:
		return ""
	}
}

func firstNonNil(m map[string]any, keys ...string) any {
	if m == nil {
		return nil
	}
	for _, key := range keys {
		if v, ok := m[key]; ok && v != nil {
			return v
		}
	}
	return nil
}

func firstMap(m map[string]any, keys ...string) map[string]any {
	for _, key := range keys {
		if sub, ok := m[key].(map[string]any); ok {
			return sub
		}
	}
	return map[string]any{}
}

func asStringSlice(v any) []string {
	switch x := v.(type) {
	case nil:
		return nil
	case []string:
		return cleanStrings(x)
	case []any:
		var out []string
		for _, item := range x {
			switch y := item.(type) {
			case string:
				out = append(out, y)
			case map[string]any:
				if s := firstString(y, "name", "text", "label", "url", "expanded_url", "id"); s != "" {
					out = append(out, s)
				}
			default:
				if s := stringFromAny(y); s != "" {
					out = append(out, s)
				}
			}
		}
		return cleanStrings(out)
	case string:
		if x == "" {
			return nil
		}
		return []string{x}
	default:
		if s := stringFromAny(x); s != "" {
			return []string{s}
		}
	}
	return nil
}

func cleanStrings(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range in {
		s = strings.TrimSpace(s)
		if s == "" || seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

func appendUnique(list []string, values ...string) []string {
	return cleanStrings(append(list, values...))
}

func linksFromPost(m map[string]any) []string {
	var out []string
	for _, key := range []string{"links", "urls", "website_urls"} {
		out = append(out, asStringSlice(m[key])...)
	}
	for _, key := range []string{"url", "href", "link", "website_url"} {
		if s := firstString(m, key); s != "" && strings.HasPrefix(strings.ToLower(s), "http") {
			out = append(out, s)
		}
	}
	return cleanStrings(out)
}

func entitiesFrom(v any) []string {
	return asStringSlice(v)
}

func hostOf(raw string) string {
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return ""
	}
	return strings.TrimPrefix(strings.ToLower(u.Hostname()), "www.")
}

func cleanHandle(s string) string {
	s = strings.TrimSpace(s)
	s = strings.TrimPrefix(s, "@")
	return strings.ToLower(s)
}

func postIDFromURL(raw string) (string, string) {
	match := statusURLPattern.FindStringSubmatch(raw)
	if len(match) != 3 {
		return "", ""
	}
	return cleanHandle(match[1]), match[2]
}

func postIDOnlyFromURL(raw string) string {
	_, id := postIDFromURL(raw)
	return id
}

func stableHash(parts ...string) string {
	h := sha256.New()
	for _, part := range parts {
		_, _ = h.Write([]byte(part))
		_, _ = h.Write([]byte{0})
	}
	return hex.EncodeToString(h.Sum(nil))
}

func optionalTime(raw string) *string {
	if raw == "" {
		return nil
	}
	s := normalizeTimeString(raw)
	return &s
}

func normalizeTimeString(raw string) string {
	if raw == "" {
		return time.Now().UTC().Format(time.RFC3339Nano)
	}
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339, "2006-01-02 15:04:05", "2006-01-02"} {
		if t, err := time.Parse(layout, raw); err == nil {
			return t.UTC().Format(time.RFC3339Nano)
		}
	}
	return raw
}

func rankFrom(m map[string]any, idx int) int {
	for _, key := range []string{"rank", "position", "index"} {
		switch x := m[key].(type) {
		case float64:
			return int(x)
		case int:
			return x
		case string:
			if n, err := strconv.Atoi(x); err == nil {
				return n
			}
		}
	}
	return idx + 1
}

func asBool(v any) bool {
	switch x := v.(type) {
	case bool:
		return x
	case string:
		x = strings.ToLower(strings.TrimSpace(x))
		return x == "true" || x == "1" || x == "yes"
	case float64:
		return x != 0
	case int:
		return x != 0
	default:
		return false
	}
}

func challengeFlag(m map[string]any) bool {
	if m == nil {
		return false
	}
	return asBool(m["challenge"]) || asBool(m["captcha"]) || asBool(m["rate_limited"]) || asBool(m["login_prompt_visible"])
}

func artifactRole(role string) string {
	if strings.Contains(strings.ToLower(role), "screenshot") {
		return "screenshot_full_page"
	}
	if role == "" {
		return "image"
	}
	return role
}

func firstInt(values ...any) int {
	for _, value := range values {
		switch x := value.(type) {
		case int:
			return x
		case int64:
			return int(x)
		case float64:
			return int(x)
		case json.Number:
			if n, err := x.Int64(); err == nil {
				return int(n)
			}
		case string:
			if n, err := strconv.Atoi(strings.TrimSpace(x)); err == nil {
				return n
			}
		}
	}
	return 0
}

func mustJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "{}"
	}
	return string(b)
}
