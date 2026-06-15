package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"github.com/cockroachdb/pebble"
	"github.com/segmentio/kafka-go"
)

const (
	captureTopic     = "evidence.capture.events.v1"
	postsObserved    = "evidence.posts.observed.v1"
	accountsObserved = "evidence.accounts.observed.v1"
	mediaObserved    = "evidence.media.observed.v1"
	searchObserved   = "evidence.search.results.v1"
	postsState       = "evidence.posts.state.v1"
	accountsState    = "evidence.accounts.state.v1"
	mediaState       = "evidence.media.state.v1"
	indexErrors      = "evidence.index.errors.v1"
)

var statusURLPattern = regexp.MustCompile(`(?i)(?:x|twitter)\.com/([^/?#]+)/status/([0-9]+)`)

type config struct {
	Brokers       []string
	GroupID       string
	PebbleDir     string
	TypesenseURL  string
	TypesenseKey  string
	QdrantURL     string
	QdrantColl    string
	ClickURL      string
	ClickDB       string
	ClickUser     string
	ClickPassword string
	HTTPAddr      string
}

type app struct {
	cfg             config
	db              *pebble.DB
	client          *http.Client
	reader          *kafka.Reader
	writers         map[string]*kafka.Writer
	processed       atomic.Uint64
	failed          atomic.Uint64
	postsIndexed    atomic.Uint64
	accountsIndexed atomic.Uint64
	mediaIndexed    atomic.Uint64
	searchIndexed   atomic.Uint64
}

type captureEvent struct {
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
	Links          []any            `json:"links"`
	Quality        map[string]any   `json:"quality"`
	Raw            map[string]any   `json:"-"`
}

type chEvidenceRow struct {
	EventID        string   `json:"event_id"`
	SchemaVersion  string   `json:"schema_version"`
	CollectorRunID string   `json:"collector_run_id"`
	SourceProject  string   `json:"source_project"`
	CaptureMethod  string   `json:"capture_method"`
	SourceKind     string   `json:"source_kind"`
	EvidenceID     string   `json:"evidence_id"`
	CanonicalURL   string   `json:"canonical_url"`
	AuthorHandle   string   `json:"author_handle"`
	Domain         string   `json:"domain"`
	Title          string   `json:"title"`
	Text           string   `json:"text"`
	Topics         []string `json:"topics"`
	Entities       []string `json:"entities"`
	Links          []string `json:"links"`
	HasMedia       uint8    `json:"has_media"`
	HasOCR         uint8    `json:"has_ocr"`
	PostedAt       *string  `json:"posted_at,omitempty"`
	CapturedAt     string   `json:"captured_at"`
	RawJSON        string   `json:"raw_json"`
}

func main() {
	cfg := loadConfig()
	db, err := openPebble(cfg.PebbleDir)
	if err != nil {
		log.Fatalf("open pebble: %v", err)
	}
	defer db.Close()

	a := &app{
		cfg:     cfg,
		db:      db,
		client:  &http.Client{Timeout: 15 * time.Second},
		writers: map[string]*kafka.Writer{},
	}
	for _, topic := range []string{postsObserved, accountsObserved, mediaObserved, searchObserved, postsState, accountsState, mediaState, indexErrors} {
		a.writers[topic] = &kafka.Writer{
			Addr:         kafka.TCP(cfg.Brokers...),
			Topic:        topic,
			Balancer:     &kafka.Hash{},
			RequiredAcks: kafka.RequireOne,
			Async:        false,
		}
	}
	defer func() {
		for _, w := range a.writers {
			_ = w.Close()
		}
	}()

	a.reader = kafka.NewReader(kafka.ReaderConfig{
		Brokers:        cfg.Brokers,
		GroupID:        cfg.GroupID,
		Topic:          captureTopic,
		StartOffset:    kafka.FirstOffset,
		MinBytes:       1,
		MaxBytes:       10 << 20,
		CommitInterval: time.Second,
	})
	defer a.reader.Close()

	go a.serveHTTP()
	log.Printf("web-osint normalizer starting group=%s brokers=%s pebble=%s", cfg.GroupID, strings.Join(cfg.Brokers, ","), cfg.PebbleDir)
	a.run(context.Background())
}

func loadConfig() config {
	return config{
		Brokers:       splitCSV(env("KAFKA_BROKERS", "127.0.0.1:19092")),
		GroupID:       env("KAFKA_GROUP_ID", "web-osint-normalizer-v1"),
		PebbleDir:     env("PEBBLE_DIR", "/data/pebble"),
		TypesenseURL:  strings.TrimRight(env("TYPESENSE_URL", "http://127.0.0.1:18108"), "/"),
		TypesenseKey:  os.Getenv("TYPESENSE_API_KEY"),
		QdrantURL:     strings.TrimRight(env("QDRANT_URL", "http://127.0.0.1:16333"), "/"),
		QdrantColl:    env("QDRANT_COLLECTION", "web_osint_evidence_v1"),
		ClickURL:      strings.TrimRight(env("CLICKHOUSE_URL", "http://127.0.0.1:18123"), "/"),
		ClickDB:       env("CLICKHOUSE_DATABASE", "web_osint"),
		ClickUser:     env("CLICKHOUSE_USER", "web_osint"),
		ClickPassword: os.Getenv("CLICKHOUSE_PASSWORD"),
		HTTPAddr:      env("HTTP_ADDR", ":8090"),
	}
}

func openPebble(dir string) (*pebble.DB, error) {
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return nil, err
	}
	return pebble.Open(dir, &pebble.Options{})
}

func (a *app) run(ctx context.Context) {
	for {
		msg, err := a.reader.FetchMessage(ctx)
		if err != nil {
			log.Printf("fetch: %v", err)
			time.Sleep(2 * time.Second)
			continue
		}
		if err := a.processMessage(ctx, msg); err != nil {
			a.failed.Add(1)
			log.Printf("process topic=%s partition=%d offset=%d: %v", msg.Topic, msg.Partition, msg.Offset, err)
			_ = a.publishError(ctx, msg, err)
			time.Sleep(500 * time.Millisecond)
			continue
		}
		if err := a.reader.CommitMessages(ctx, msg); err != nil {
			log.Printf("commit offset=%d: %v", msg.Offset, err)
			continue
		}
		a.processed.Add(1)
	}
}

func (a *app) processMessage(ctx context.Context, msg kafka.Message) error {
	var raw map[string]any
	if err := json.Unmarshal(msg.Value, &raw); err != nil {
		return err
	}
	var ev captureEvent
	if err := json.Unmarshal(msg.Value, &ev); err != nil {
		return err
	}
	ev.Raw = raw
	if ev.SchemaVersion == "" {
		ev.SchemaVersion = "v1"
	}
	if ev.CapturedAt == "" {
		ev.CapturedAt = time.Now().UTC().Format(time.RFC3339Nano)
	}
	eventID := fmt.Sprintf("%s:%d", ev.CollectorRunID, ev.EventIndex)
	if err := a.setPebble("capture/"+eventID, envelope("capture", eventID, raw, msg)); err != nil {
		return err
	}

	rootRow := chEvidenceRow{
		EventID:        eventID,
		SchemaVersion:  ev.SchemaVersion,
		CollectorRunID: ev.CollectorRunID,
		SourceProject:  ev.SourceProject,
		CaptureMethod:  ev.CaptureMethod,
		SourceKind:     sourceKindForCapture(ev),
		EvidenceID:     "capture/" + eventID,
		CanonicalURL:   ev.PageURL,
		Domain:         hostOf(ev.PageURL),
		Title:          ev.PageTitle,
		Text:           textForCapture(ev),
		Topics:         asStringSlice(raw["topics"]),
		Entities:       entitiesFrom(raw["entities"]),
		Links:          linksFromAny(ev.Links),
		HasMedia:       boolByte(len(ev.Media) > 0),
		HasOCR:         boolByte(asBool(raw["has_ocr"]) || hasOCRInMedia(ev.Media)),
		CapturedAt:     normalizeTimeString(ev.CapturedAt),
		RawJSON:        string(msg.Value),
	}
	if err := a.insertClickEvidence(ctx, []chEvidenceRow{rootRow}); err != nil {
		return err
	}
	if err := a.upsertTypesenseEvidence(ctx, rootRow, map[string]any{"quality": ev.Quality}); err != nil {
		return err
	}
	if err := a.insertCollectorRun(ctx, ev); err != nil {
		return err
	}

	for i, post := range ev.Posts {
		if err := a.handlePost(ctx, ev, msg, i, post); err != nil {
			return err
		}
	}
	for i, account := range ev.Accounts {
		if err := a.handleAccount(ctx, ev, msg, i, account); err != nil {
			return err
		}
	}
	for i, media := range ev.Media {
		if err := a.handleMedia(ctx, ev, msg, i, media); err != nil {
			return err
		}
	}
	for i, result := range searchResultsFrom(ev.Raw, ev.Context) {
		if err := a.handleSearchResult(ctx, ev, msg, i, result); err != nil {
			return err
		}
	}
	return nil
}

func (a *app) handlePost(ctx context.Context, ev captureEvent, msg kafka.Message, idx int, post map[string]any) error {
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
	postedAt := optionalTime(firstString(post, "posted_at", "created_at", "time", "timestamp"))
	links := linksFromPost(post)
	topics := asStringSlice(post["topics"])
	entities := entitiesFrom(post["entities"])
	mediaIDs := asStringSlice(firstNonNil(post, "media_ids", "media"))
	text := firstString(post, "text", "full_text", "content", "body")

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
		"posted_at":        postedAt,
		"text":             text,
		"lang":             firstString(post, "lang", "language"),
		"links":            links,
		"media_ids":        mediaIDs,
		"topics":           topics,
		"entities":         entities,
		"quality":          firstMap(post, "quality"),
		"raw":              post,
	}
	if post["vectors"] != nil {
		observed["vectors"] = post["vectors"]
	}
	if err := a.publishJSON(ctx, postsObserved, postID, observed); err != nil {
		return err
	}
	state := map[string]any{
		"post_id":        postID,
		"canonical_url":  canonicalURL,
		"author_handle":  authorHandle,
		"text":           text,
		"topics":         topics,
		"entities":       entities,
		"last_seen_at":   normalizeTimeString(ev.CapturedAt),
		"source_project": ev.SourceProject,
		"observation":    observed,
	}
	if err := a.publishJSON(ctx, postsState, postID, state); err != nil {
		return err
	}
	if err := a.setPebble("post/"+postID, envelope("post", postID, state, msg)); err != nil {
		return err
	}
	row := chEvidenceRow{
		EventID:        observationID,
		SchemaVersion:  "v1",
		CollectorRunID: ev.CollectorRunID,
		SourceProject:  ev.SourceProject,
		CaptureMethod:  ev.CaptureMethod,
		SourceKind:     "x_post",
		EvidenceID:     postID,
		CanonicalURL:   canonicalURL,
		AuthorHandle:   authorHandle,
		Domain:         hostOf(canonicalURL),
		Title:          firstString(post, "title"),
		Text:           text,
		Topics:         topics,
		Entities:       entities,
		Links:          links,
		HasMedia:       boolByte(len(mediaIDs) > 0 || hasAny(post, "media", "images", "video")),
		HasOCR:         boolByte(asBool(post["has_ocr"]) || firstString(post, "ocr_text") != ""),
		PostedAt:       postedAt,
		CapturedAt:     normalizeTimeString(ev.CapturedAt),
		RawJSON:        mustJSON(observed),
	}
	if err := a.insertClickEvidence(ctx, []chEvidenceRow{row}); err != nil {
		return err
	}
	if err := a.upsertTypesenseEvidence(ctx, row, observed); err != nil {
		return err
	}
	_ = a.upsertQdrantIfVector(ctx, postID, observed)
	a.postsIndexed.Add(1)
	return nil
}

func (a *app) handleAccount(ctx context.Context, ev captureEvent, msg kafka.Message, idx int, account map[string]any) error {
	handle := cleanHandle(firstString(account, "handle", "author_handle", "screen_name", "username"))
	if handle == "" {
		handle = stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "account", strconv.Itoa(idx), mustJSON(account))[:16]
	}
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "account", handle, strconv.Itoa(idx))
	links := linksFromPost(account)
	topics := asStringSlice(account["topics"])
	entities := entitiesFrom(account["entities"])
	text := firstString(account, "bio", "description", "text")
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
		"bio":               text,
		"website_urls":      links,
		"topics":            topics,
		"entities":          entities,
		"raw":               account,
	}
	if account["vectors"] != nil {
		observed["vectors"] = account["vectors"]
	}
	if err := a.publishJSON(ctx, accountsObserved, handle, observed); err != nil {
		return err
	}
	if err := a.publishJSON(ctx, accountsState, handle, observed); err != nil {
		return err
	}
	if err := a.setPebble("account/"+handle, envelope("account", handle, observed, msg)); err != nil {
		return err
	}
	row := chEvidenceRow{
		EventID:        observationID,
		SchemaVersion:  "v1",
		CollectorRunID: ev.CollectorRunID,
		SourceProject:  ev.SourceProject,
		CaptureMethod:  ev.CaptureMethod,
		SourceKind:     "x_account",
		EvidenceID:     handle,
		CanonicalURL:   firstString(account, "profile_url", "url"),
		AuthorHandle:   handle,
		Domain:         hostOf(firstString(account, "profile_url", "url")),
		Title:          firstString(account, "display_name", "name", "author_name"),
		Text:           text,
		Topics:         topics,
		Entities:       entities,
		Links:          links,
		HasMedia:       boolByte(firstString(account, "profile_image_url", "avatar_url") != ""),
		CapturedAt:     normalizeTimeString(ev.CapturedAt),
		RawJSON:        mustJSON(observed),
	}
	if err := a.insertClickEvidence(ctx, []chEvidenceRow{row}); err != nil {
		return err
	}
	if err := a.upsertTypesenseEvidence(ctx, row, observed); err != nil {
		return err
	}
	_ = a.upsertQdrantIfVector(ctx, "account/"+handle, observed)
	a.accountsIndexed.Add(1)
	return nil
}

func (a *app) handleMedia(ctx context.Context, ev captureEvent, msg kafka.Message, idx int, media map[string]any) error {
	mediaID := firstString(media, "media_id", "id", "sha256", "url", "local_path")
	if mediaID == "" {
		mediaID = stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "media", strconv.Itoa(idx), mustJSON(media))[:32]
	}
	observationID := stableHash(ev.CollectorRunID, strconv.Itoa(ev.EventIndex), "media", mediaID, strconv.Itoa(idx))
	text := firstString(media, "ocr_text", "caption", "alt_text", "description")
	links := linksFromPost(media)
	topics := asStringSlice(media["topics"])
	entities := entitiesFrom(media["entities"])
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
		"topics":           topics,
		"entities":         entities,
		"raw":              media,
	}
	if media["vectors"] != nil {
		observed["vectors"] = media["vectors"]
	}
	if err := a.publishJSON(ctx, mediaObserved, mediaID, observed); err != nil {
		return err
	}
	if err := a.publishJSON(ctx, mediaState, mediaID, observed); err != nil {
		return err
	}
	if err := a.setPebble("media/"+mediaID, envelope("media", mediaID, observed, msg)); err != nil {
		return err
	}
	row := chEvidenceRow{
		EventID:        observationID,
		SchemaVersion:  "v1",
		CollectorRunID: ev.CollectorRunID,
		SourceProject:  ev.SourceProject,
		CaptureMethod:  ev.CaptureMethod,
		SourceKind:     "media",
		EvidenceID:     mediaID,
		CanonicalURL:   firstString(media, "url", "src"),
		Domain:         hostOf(firstString(media, "url", "src")),
		Title:          firstString(media, "caption", "alt_text"),
		Text:           text,
		Topics:         topics,
		Entities:       entities,
		Links:          links,
		HasMedia:       1,
		HasOCR:         boolByte(firstString(media, "ocr_text") != ""),
		CapturedAt:     normalizeTimeString(ev.CapturedAt),
		RawJSON:        mustJSON(observed),
	}
	if err := a.insertClickEvidence(ctx, []chEvidenceRow{row}); err != nil {
		return err
	}
	if err := a.upsertTypesenseEvidence(ctx, row, observed); err != nil {
		return err
	}
	_ = a.upsertQdrantIfVector(ctx, "media/"+mediaID, observed)
	a.mediaIndexed.Add(1)
	return nil
}

func (a *app) handleSearchResult(ctx context.Context, ev captureEvent, msg kafka.Message, idx int, result map[string]any) error {
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
	if err := a.publishJSON(ctx, searchObserved, id, observed); err != nil {
		return err
	}
	if err := a.setPebble("search/"+id, envelope("search_result", id, observed, msg)); err != nil {
		return err
	}
	row := chEvidenceRow{
		EventID:        id,
		SchemaVersion:  "v1",
		CollectorRunID: ev.CollectorRunID,
		SourceProject:  ev.SourceProject,
		CaptureMethod:  ev.CaptureMethod,
		SourceKind:     "search_result",
		EvidenceID:     id,
		CanonicalURL:   resultURL,
		Domain:         hostOf(resultURL),
		Title:          firstString(result, "title"),
		Text:           firstString(result, "snippet", "description", "text"),
		Links:          []string{resultURL},
		CapturedAt:     normalizeTimeString(ev.CapturedAt),
		RawJSON:        mustJSON(observed),
	}
	if err := a.insertClickEvidence(ctx, []chEvidenceRow{row}); err != nil {
		return err
	}
	if err := a.upsertTypesenseEvidence(ctx, row, observed); err != nil {
		return err
	}
	a.searchIndexed.Add(1)
	return nil
}

func (a *app) publishJSON(ctx context.Context, topic, key string, v any) error {
	payload, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return a.writers[topic].WriteMessages(ctx, kafka.Message{Key: []byte(key), Value: payload})
}

func (a *app) publishError(ctx context.Context, msg kafka.Message, err error) error {
	v := map[string]any{
		"schema_version": "v1",
		"topic":          msg.Topic,
		"partition":      msg.Partition,
		"offset":         msg.Offset,
		"error":          err.Error(),
		"created_at":     time.Now().UTC().Format(time.RFC3339Nano),
	}
	return a.publishJSON(ctx, indexErrors, fmt.Sprintf("%s/%d/%d", msg.Topic, msg.Partition, msg.Offset), v)
}

func (a *app) setPebble(key string, value map[string]any) error {
	payload, err := json.Marshal(value)
	if err != nil {
		return err
	}
	return a.db.Set([]byte(key), payload, pebble.Sync)
}

func envelope(kind, id string, value any, msg kafka.Message) map[string]any {
	return map[string]any{
		"kind":         kind,
		"id":           id,
		"updated_at":   time.Now().UTC().Format(time.RFC3339Nano),
		"source_topic": msg.Topic,
		"partition":    msg.Partition,
		"offset":       msg.Offset,
		"value":        value,
	}
}

func (a *app) insertClickEvidence(ctx context.Context, rows []chEvidenceRow) error {
	if len(rows) == 0 || a.cfg.ClickPassword == "" {
		return nil
	}
	var buf bytes.Buffer
	for _, row := range rows {
		b, err := json.Marshal(row)
		if err != nil {
			return err
		}
		buf.Write(b)
		buf.WriteByte('\n')
	}
	return a.clickhousePost(ctx, "INSERT INTO evidence_events FORMAT JSONEachRow", &buf)
}

func (a *app) insertCollectorRun(ctx context.Context, ev captureEvent) error {
	if a.cfg.ClickPassword == "" || ev.CollectorRunID == "" {
		return nil
	}
	row := map[string]any{
		"collector_run_id": ev.CollectorRunID,
		"source_project":   ev.SourceProject,
		"capture_method":   ev.CaptureMethod,
		"started_at":       normalizeTimeString(ev.CapturedAt),
		"finished_at":      nil,
		"status":           "observed",
		"records_seen":     uint64(1),
		"records_emitted":  uint64(len(ev.Posts) + len(ev.Accounts) + len(ev.Media)),
		"challenge":        boolByte(challengeFlag(ev.Quality)),
		"partial":          boolByte(asBool(ev.Quality["partial"])),
		"notes":            "",
	}
	payload, err := json.Marshal(row)
	if err != nil {
		return err
	}
	payload = append(payload, '\n')
	return a.clickhousePost(ctx, "INSERT INTO collector_runs FORMAT JSONEachRow", bytes.NewReader(payload))
}

func (a *app) clickhousePost(ctx context.Context, query string, body io.Reader) error {
	u, err := url.Parse(a.cfg.ClickURL + "/")
	if err != nil {
		return err
	}
	q := u.Query()
	q.Set("database", a.cfg.ClickDB)
	q.Set("query", query)
	q.Set("date_time_input_format", "best_effort")
	q.Set("input_format_null_as_default", "1")
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, u.String(), body)
	if err != nil {
		return err
	}
	req.SetBasicAuth(a.cfg.ClickUser, a.cfg.ClickPassword)
	resp, err := a.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("clickhouse status=%d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	return nil
}

func (a *app) upsertTypesenseEvidence(ctx context.Context, row chEvidenceRow, observed map[string]any) error {
	if a.cfg.TypesenseKey == "" || row.EvidenceID == "" {
		return nil
	}
	authorName := stringFromAny(observed["author_name"])
	if authorName == "" {
		authorName = stringFromAny(observed["display_name"])
	}
	if authorName == "" && row.SourceKind == "x_account" {
		authorName = row.Title
	}
	doc := map[string]any{
		"id":              row.EvidenceID,
		"canonical_url":   row.CanonicalURL,
		"author_handle":   row.AuthorHandle,
		"author_name":     authorName,
		"source_projects": cleanStrings([]string{row.SourceProject}),
		"source_kind":     row.SourceKind,
		"topics":          row.Topics,
		"entities":        row.Entities,
		"captured_at":     unixSeconds(row.CapturedAt),
		"text":            row.Text,
		"links":           row.Links,
		"link_hosts":      hostsOf(row.Links),
		"has_ocr":         row.HasOCR == 1,
		"quality_flags":   qualityFlags(firstMap(observed, "quality")),
	}
	if row.PostedAt != nil {
		doc["posted_at"] = unixSeconds(*row.PostedAt)
	}
	if row.HasMedia == 1 {
		mediaKind := stringFromAny(observed["media_kind"])
		if mediaKind == "" {
			mediaKind = stringFromAny(observed["kind"])
		}
		if mediaKind == "" {
			mediaKind = "unknown"
		}
		doc["media_kinds"] = []string{mediaKind}
		doc["has_screenshot"] = strings.Contains(strings.ToLower(mediaKind), "screenshot")
	}
	payload, err := json.Marshal(doc)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, a.cfg.TypesenseURL+"/collections/evidence_posts/documents?action=upsert", bytes.NewReader(payload))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-TYPESENSE-API-KEY", a.cfg.TypesenseKey)
	resp, err := a.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("typesense status=%d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	return nil
}

func (a *app) upsertQdrantIfVector(ctx context.Context, evidenceID string, observed map[string]any) error {
	vectors := vectorsFrom(observed)
	if len(vectors) == 0 {
		return nil
	}
	payload := map[string]any{
		"evidence_id":     evidenceID,
		"source_project":  stringFromAny(observed["source_project"]),
		"author_handle":   stringFromAny(observed["author_handle"]),
		"canonical_url":   stringFromAny(observed["canonical_url"]),
		"topics":          asStringSlice(observed["topics"]),
		"entities":        entitiesFrom(observed["entities"]),
		"captured_at_day": dayString(stringFromAny(observed["captured_at"])),
	}
	point := map[string]any{"id": uuidFrom(evidenceID), "vector": vectors, "payload": payload}
	body := map[string]any{"points": []any{point}}
	b, err := json.Marshal(body)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, a.cfg.QdrantURL+"/collections/"+a.cfg.QdrantColl+"/points?wait=true", bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := a.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 4096))
		return fmt.Errorf("qdrant status=%d: %s", resp.StatusCode, strings.TrimSpace(string(msg)))
	}
	return nil
}

func (a *app) serveHTTP() {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}` + "\n"))
	})
	mux.HandleFunc("/stats", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{
			"processed":        a.processed.Load(),
			"failed":           a.failed.Load(),
			"posts_indexed":    a.postsIndexed.Load(),
			"accounts_indexed": a.accountsIndexed.Load(),
			"media_indexed":    a.mediaIndexed.Load(),
			"search_indexed":   a.searchIndexed.Load(),
		})
	})
	mux.HandleFunc("/pebble", func(w http.ResponseWriter, r *http.Request) {
		limit := 250
		if raw := r.URL.Query().Get("limit"); raw != "" {
			if parsed, err := strconv.Atoi(raw); err == nil && parsed > 0 {
				limit = parsed
			}
		}
		if limit > 2000 {
			limit = 2000
		}
		info, err := a.pebbleInfo(limit)
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		writeJSON(w, info)
	})
	mux.HandleFunc("/lookup", func(w http.ResponseWriter, r *http.Request) {
		key := r.URL.Query().Get("key")
		if key == "" {
			http.Error(w, "missing key", http.StatusBadRequest)
			return
		}
		value, closer, err := a.db.Get([]byte(key))
		if errors.Is(err, pebble.ErrNotFound) {
			http.NotFound(w, r)
			return
		}
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer closer.Close()
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write(value)
		_, _ = w.Write([]byte("\n"))
	})
	if err := http.ListenAndServe(a.cfg.HTTPAddr, mux); err != nil {
		log.Fatalf("http: %v", err)
	}
}

func (a *app) pebbleInfo(limit int) (map[string]any, error) {
	iter, err := a.db.NewIter(&pebble.IterOptions{})
	if err != nil {
		return nil, err
	}
	defer iter.Close()

	type prefixStats struct {
		Prefix     string   `json:"prefix"`
		Keys       uint64   `json:"keys"`
		ValueBytes uint64   `json:"value_bytes"`
		Samples    []string `json:"samples"`
	}

	prefixes := map[string]*prefixStats{}
	samples := []string{}
	var totalKeys uint64
	var totalValueBytes uint64

	for ok := iter.First(); ok; ok = iter.Next() {
		key := string(iter.Key())
		valueBytes := uint64(len(iter.Value()))
		prefix := key
		if parts := strings.SplitN(key, "/", 2); len(parts) > 1 {
			prefix = parts[0] + "/"
		}
		stat := prefixes[prefix]
		if stat == nil {
			stat = &prefixStats{Prefix: prefix}
			prefixes[prefix] = stat
		}
		stat.Keys++
		stat.ValueBytes += valueBytes
		if len(stat.Samples) < 8 {
			stat.Samples = append(stat.Samples, key)
		}
		if len(samples) < limit {
			samples = append(samples, key)
		}
		totalKeys++
		totalValueBytes += valueBytes
	}
	if err := iter.Error(); err != nil {
		return nil, err
	}

	prefixRows := make([]prefixStats, 0, len(prefixes))
	for _, stat := range prefixes {
		prefixRows = append(prefixRows, *stat)
	}
	return map[string]any{
		"metrics":           a.db.Metrics(),
		"total_keys":        totalKeys,
		"total_value_bytes": totalValueBytes,
		"prefixes":          prefixRows,
		"sample_keys":       samples,
		"sample_limit":      limit,
	}, nil
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	b, _ := json.MarshalIndent(v, "", "  ")
	_, _ = w.Write(b)
	_, _ = w.Write([]byte("\n"))
}

func sourceKindForCapture(ev captureEvent) string {
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

func textForCapture(ev captureEvent) string {
	if ev.Context != nil {
		for _, key := range []string{"query", "text", "summary"} {
			if s := stringFromAny(ev.Context[key]); s != "" {
				return s
			}
		}
	}
	return ev.PageTitle
}

func firstString(m map[string]any, keys ...string) string {
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

func splitCSV(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		part = strings.TrimSpace(part)
		if part != "" {
			out = append(out, part)
		}
	}
	return out
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func firstNonNil(m map[string]any, keys ...string) any {
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

func linksFromAny(items []any) []string {
	var out []string
	for _, item := range items {
		switch x := item.(type) {
		case string:
			out = append(out, x)
		case map[string]any:
			out = append(out, firstString(x, "url", "expanded_url", "href", "link"))
		}
	}
	return cleanStrings(out)
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

func hostsOf(urls []string) []string {
	var out []string
	for _, raw := range urls {
		out = append(out, hostOf(raw))
	}
	return cleanStrings(out)
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

func uuidFrom(s string) string {
	h := stableHash(s)
	return fmt.Sprintf("%s-%s-%s-%s-%s", h[0:8], h[8:12], h[12:16], h[16:20], h[20:32])
}

func boolByte(v bool) uint8 {
	if v {
		return 1
	}
	return 0
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

func hasAny(m map[string]any, keys ...string) bool {
	for _, key := range keys {
		if v, ok := m[key]; ok && v != nil {
			switch x := v.(type) {
			case []any:
				if len(x) > 0 {
					return true
				}
			case string:
				if x != "" {
					return true
				}
			default:
				return true
			}
		}
	}
	return false
}

func hasOCRInMedia(media []map[string]any) bool {
	for _, m := range media {
		if firstString(m, "ocr_text") != "" || asBool(m["has_ocr"]) {
			return true
		}
	}
	return false
}

func challengeFlag(m map[string]any) bool {
	if m == nil {
		return false
	}
	return asBool(m["challenge"]) || asBool(m["captcha"]) || asBool(m["rate_limited"]) || asBool(m["login_prompt_visible"])
}

func qualityFlags(m map[string]any) []string {
	var out []string
	for _, key := range []string{"challenge", "captcha", "rate_limited", "login_prompt_visible", "partial"} {
		if asBool(m[key]) {
			out = append(out, key)
		}
	}
	return out
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

func unixSeconds(raw string) int64 {
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339, "2006-01-02 15:04:05", "2006-01-02"} {
		if t, err := time.Parse(layout, raw); err == nil {
			return t.Unix()
		}
	}
	return time.Now().Unix()
}

func dayString(raw string) string {
	if raw == "" {
		return ""
	}
	for _, layout := range []string{time.RFC3339Nano, time.RFC3339, "2006-01-02 15:04:05", "2006-01-02"} {
		if t, err := time.Parse(layout, raw); err == nil {
			return t.UTC().Format("2006-01-02")
		}
	}
	if len(raw) >= 10 {
		return raw[:10]
	}
	return ""
}

func searchResultsFrom(raw map[string]any, context map[string]any) []map[string]any {
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

func vectorsFrom(observed map[string]any) map[string][]float32 {
	root, _ := observed["vectors"].(map[string]any)
	if root == nil {
		root, _ = observed["embedding"].(map[string]any)
	}
	out := map[string][]float32{}
	for _, name := range []string{"text_dense", "ocr_dense", "caption_dense", "account_dense"} {
		vec := floatSlice(root[name])
		if len(vec) > 0 {
			out[name] = vec
		}
	}
	return out
}

func floatSlice(v any) []float32 {
	switch x := v.(type) {
	case []float32:
		return x
	case []float64:
		out := make([]float32, 0, len(x))
		for _, f := range x {
			out = append(out, float32(f))
		}
		return out
	case []any:
		out := make([]float32, 0, len(x))
		for _, item := range x {
			switch y := item.(type) {
			case float64:
				out = append(out, float32(y))
			case float32:
				out = append(out, y)
			case json.Number:
				if f, err := y.Float64(); err == nil {
					out = append(out, float32(f))
				}
			}
		}
		return out
	default:
		return nil
	}
}

func mustJSON(v any) string {
	b, err := json.Marshal(v)
	if err != nil {
		return "{}"
	}
	return string(b)
}
