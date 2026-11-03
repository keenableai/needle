PREVIEW_DIR ?= .preview
PREVIEW_PORT ?= 8765
PREVIEW_ORIGIN ?= https://keenableai.github.io/needle/data

PREVIEW_FILES := history.jsonl overlap.jsonl uniqueness.jsonl families.json catalog.json runs.json ci.json latest_news.json latest_finance.json latest_scholar.json latest_legal.json latest_agentic_rare.json

.PHONY: preview preview-sync preview-stop

preview: preview-sync
	@if lsof -ti tcp:$(PREVIEW_PORT) >/dev/null 2>&1; then \
	  echo "port $(PREVIEW_PORT) is already in use; run: make preview-stop"; \
	  exit 1; \
	fi
	@printf '\nPreview ready. Open:\n'
	@printf '  home         http://127.0.0.1:%s/\n' "$(PREVIEW_PORT)"
	@printf '  compare      http://127.0.0.1:%s/compare/\n' "$(PREVIEW_PORT)"
	@printf '  news         http://127.0.0.1:%s/news/\n' "$(PREVIEW_PORT)"
	@printf '  finance      http://127.0.0.1:%s/finance/\n' "$(PREVIEW_PORT)"
	@printf '  scholar      http://127.0.0.1:%s/scholar/\n' "$(PREVIEW_PORT)"
	@printf '  legal        http://127.0.0.1:%s/legal/\n' "$(PREVIEW_PORT)"
	@printf '  methodology  http://127.0.0.1:%s/methodology/\n' "$(PREVIEW_PORT)"
	@printf '\nCtrl+C to stop, or: make preview-stop\n'
	@printf 'Judgement browser fetches Hugging Face artifacts and may 404 here.\n\n'
	cd $(PREVIEW_DIR) && python3 -m http.server $(PREVIEW_PORT) --bind 127.0.0.1

preview-sync:
	@test -n "$(PREVIEW_DIR)" && test "$(PREVIEW_DIR)" != "/" && test "$(PREVIEW_DIR)" != "."
	rm -rf "$(PREVIEW_DIR)"
	mkdir -p "$(PREVIEW_DIR)/data"
	cp -R dashboard/. "$(PREVIEW_DIR)/"
	@if [ -d data ]; then \
	  echo "seeding $(PREVIEW_DIR)/data from local data/"; \
	  cp -R data/. "$(PREVIEW_DIR)/data/"; \
	fi
	@ok=0; miss=0; \
	for f in $(PREVIEW_FILES); do \
	  if curl -fsSL --connect-timeout 10 --max-time 120 \
	      -o "$(PREVIEW_DIR)/data/$$f.part" "$(PREVIEW_ORIGIN)/$$f" 2>/dev/null; then \
	    mv "$(PREVIEW_DIR)/data/$$f.part" "$(PREVIEW_DIR)/data/$$f"; \
	    echo "fetched $$f"; \
	    ok=$$((ok+1)); \
	  else \
	    rm -f "$(PREVIEW_DIR)/data/$$f.part"; \
	    if [ -f "$(PREVIEW_DIR)/data/$$f" ]; then \
	      echo "kept local $$f"; \
	    else \
	      echo "missing $$f"; \
	      miss=$$((miss+1)); \
	    fi; \
	  fi; \
	done; \
	echo "data: $$ok live, $$miss missing"

preview-stop:
	@pids=$$(lsof -ti tcp:$(PREVIEW_PORT) 2>/dev/null || true); \
	if [ -n "$$pids" ]; then kill $$pids && echo "stopped :$(PREVIEW_PORT)"; \
	else echo "nothing on :$(PREVIEW_PORT)"; fi
