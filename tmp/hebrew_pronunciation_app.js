
    const STORAGE_KEY = "hebrew-pronunciation-transcript-v1";
    const EMPTY_SELECTION = "Click a word or phrase on the right.";
    const state = {
      seed: null,
      working: null,
      currentPageIndex: 0,
      selectedSegmentId: null
    };

    const elements = {
      addSegmentForm: document.getElementById("addSegmentForm"),
      addSegmentSection: document.getElementById("addSegmentSection"),
      addSegmentText: document.getElementById("addSegmentText"),
      copyText: document.getElementById("copyText"),
      errorBanner: document.getElementById("errorBanner"),
      exportTranscript: document.getElementById("exportTranscript"),
      nextPage: document.getElementById("nextPage"),
      openTranslate: document.getElementById("openTranslate"),
      pageCounter: document.getElementById("pageCounter"),
      pageImage: document.getElementById("pageImage"),
      pageNotes: document.getElementById("pageNotes"),
      pageTitle: document.getElementById("pageTitle"),
      prevPage: document.getElementById("prevPage"),
      resetTranscript: document.getElementById("resetTranscript"),
      sectionList: document.getElementById("sectionList"),
      selectedMeta: document.getElementById("selectedMeta"),
      selectedText: document.getElementById("selectedText"),
      speakText: document.getElementById("speakText"),
      storageStatus: document.getElementById("storageStatus"),
      transcriptTitle: document.getElementById("transcriptTitle")
    };

    function deepClone(value) {
      return JSON.parse(JSON.stringify(value));
    }

    function saveLocalState() {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.working));
      renderStorageStatus();
    }

    function renderStorageStatus() {
      const saved = localStorage.getItem(STORAGE_KEY);
      elements.storageStatus.textContent = saved
        ? "Local edits saved in this browser session."
        : "Using the seed transcript from transcript.json.";
    }

    function makeSegmentId(pageNumber, index) {
      return "page-" + String(pageNumber).padStart(3, "0") + "-segment-" + String(index + 1).padStart(3, "0");
    }

    function normaliseData(payload) {
      payload.pages = (payload.pages || []).map(function (page, pageIndex) {
        const normalised = Object.assign({}, page);
        normalised.page = page.page || pageIndex + 1;
        normalised.notes = Array.isArray(page.notes) ? page.notes : [];
        normalised.segments = Array.isArray(page.segments) ? page.segments : [];
        normalised.segments = normalised.segments.map(function (segment, segmentIndex) {
          return {
            id: segment.id || makeSegmentId(normalised.page, segmentIndex),
            text: segment.text || "",
            section: segment.section || "Transcript",
            kind: segment.kind || (segment.text && segment.text.indexOf(" ") >= 0 ? "phrase" : "word")
          };
        });
        return normalised;
      });
      return payload;
    }

    async function loadTranscript() {
      try {
        const response = await fetch("./transcript.json", { cache: "no-store" });
        if (!response.ok) {
          throw new Error("Transcript fetch failed: " + response.status);
        }

        state.seed = normaliseData(await response.json());
        const saved = localStorage.getItem(STORAGE_KEY);
        state.working = saved ? normaliseData(JSON.parse(saved)) : deepClone(state.seed);
        renderStorageStatus();
        renderPage();
      } catch (error) {
        elements.errorBanner.classList.remove("hidden");
        elements.storageStatus.textContent = "Waiting for transcript data.";
        console.error(error);
      }
    }

    function currentPage() {
      return state.working.pages[state.currentPageIndex];
    }

    function findSelectedSegment() {
      const page = currentPage();
      if (!page || !state.selectedSegmentId) {
        return null;
      }
      return page.segments.find(function (segment) {
        return segment.id === state.selectedSegmentId;
      }) || null;
    }

    function groupSegments(page) {
      const order = [];
      const groups = new Map();

      page.segments.forEach(function (segment) {
        const label = segment.section || "Transcript";
        if (!groups.has(label)) {
          groups.set(label, []);
          order.push(label);
        }
        groups.get(label).push(segment);
      });

      return order.map(function (label) {
        return [label, groups.get(label)];
      });
    }

    function renderNotes(notes) {
      elements.pageNotes.replaceChildren();
      notes.forEach(function (note) {
        const item = document.createElement("li");
        item.textContent = note;
        elements.pageNotes.appendChild(item);
      });
    }

    function beginInlineEdit(segmentId) {
      const chip = document.querySelector('[data-segment-id="' + segmentId + '"]');
      const segment = findSelectedSegment() && findSelectedSegment().id === segmentId
        ? findSelectedSegment()
        : currentPage().segments.find(function (entry) {
            return entry.id === segmentId;
          });

      if (!chip || !segment) {
        return;
      }

      chip.classList.add("is-editing");
      chip.replaceChildren();

      const input = document.createElement("input");
      input.className = "chip-editor";
      input.type = "text";
      input.value = segment.text;
      input.dir = "rtl";
      chip.appendChild(input);
      input.focus();
      input.select();

      let handled = false;

      function finish(save) {
        if (handled) {
          return;
        }
        handled = true;

        if (save) {
          const value = input.value.trim();
          if (value) {
            segment.text = value;
            segment.kind = value.indexOf(" ") >= 0 ? "phrase" : "word";
            saveLocalState();
          }
        }

        renderPage();
      }

      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter") {
          event.preventDefault();
          finish(true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          finish(false);
        }
      });

      input.addEventListener("blur", function () {
        finish(true);
      });
    }

    function renderSegments(page) {
      elements.sectionList.replaceChildren();

      if (!page.segments.length) {
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.textContent = "No verified transcript is loaded for this page yet. Add a word or phrase below as you verify it against the scan.";
        elements.sectionList.appendChild(empty);
        return;
      }

      groupSegments(page).forEach(function (entry) {
        const sectionName = entry[0];
        const segments = entry[1];

        const card = document.createElement("section");
        card.className = "section-card";

        const heading = document.createElement("div");
        heading.innerHTML = '<p class="section-label"></p>';
        heading.querySelector(".section-label").textContent = sectionName;
        card.appendChild(heading);

        const grid = document.createElement("div");
        grid.className = "segment-grid";

        segments.forEach(function (segment) {
          const chip = document.createElement("button");
          chip.type = "button";
          chip.className = "segment-chip";
          chip.dataset.segmentId = segment.id;

          if (segment.id === state.selectedSegmentId) {
            chip.classList.add("selected");
          }

          const text = document.createElement("span");
          text.className = "segment-text";
          text.textContent = segment.text;

          const kind = document.createElement("span");
          kind.className = "chip-kind";
          kind.textContent = segment.kind;

          chip.appendChild(text);
          chip.appendChild(kind);

          chip.addEventListener("click", function () {
            state.selectedSegmentId = segment.id;
            renderPage();
          });

          chip.addEventListener("dblclick", function () {
            state.selectedSegmentId = segment.id;
            renderPage();
            beginInlineEdit(segment.id);
          });

          grid.appendChild(chip);
        });

        card.appendChild(grid);
        elements.sectionList.appendChild(card);
      });
    }

    function renderSelection() {
      const segment = findSelectedSegment();

      if (!segment) {
        elements.selectedText.textContent = EMPTY_SELECTION;
        elements.selectedMeta.textContent = "Double-click any chip to edit it inline, then use Export edits when you want a JSON snapshot.";
        elements.copyText.disabled = true;
        elements.openTranslate.disabled = true;
        elements.speakText.disabled = true;
        return;
      }

      elements.selectedText.textContent = segment.text;
      elements.selectedMeta.textContent = "Selected from " + (segment.section || "Transcript") + ".";
      elements.copyText.disabled = false;
      elements.openTranslate.disabled = false;
      elements.speakText.disabled = false;
    }

    function renderPage() {
      if (!state.working || !state.working.pages.length) {
        return;
      }

      const page = currentPage();
      elements.pageTitle.textContent = page.title || "Pilot page " + page.page;
      elements.transcriptTitle.textContent = "Verified words and phrases";
      elements.pageCounter.textContent = "Page " + page.page + " of " + state.working.pages.length;
      elements.pageImage.src = page.image;
      elements.pageImage.alt = "Scanned PDF page " + page.page;
      elements.prevPage.disabled = state.currentPageIndex === 0;
      elements.nextPage.disabled = state.currentPageIndex === state.working.pages.length - 1;
      renderNotes(page.notes || []);
      renderSegments(page);

      const selectedStillExists = page.segments.some(function (segment) {
        return segment.id === state.selectedSegmentId;
      });

      if (!selectedStillExists) {
        state.selectedSegmentId = null;
      }

      renderSelection();
    }

    function changePage(delta) {
      if (!state.working) {
        return;
      }

      const nextIndex = state.currentPageIndex + delta;
      if (nextIndex < 0 || nextIndex >= state.working.pages.length) {
        return;
      }

      state.currentPageIndex = nextIndex;
      state.selectedSegmentId = null;
      renderPage();
    }

    async function copySelectedText() {
      const segment = findSelectedSegment();
      if (!segment) {
        return;
      }

      try {
        await navigator.clipboard.writeText(segment.text);
        elements.selectedMeta.textContent = "Copied to clipboard.";
      } catch (error) {
        elements.selectedMeta.textContent = "Clipboard access failed in this browser. You can still select the text manually.";
        console.error(error);
      }
    }

    function openSelectedInTranslate() {
      const segment = findSelectedSegment();
      if (!segment) {
        return;
      }

      const url = "https://translate.google.com/?sl=iw&tl=en&text=" + encodeURIComponent(segment.text) + "&op=translate";
      window.open(url, "_blank", "noopener");
    }

    function speakSelectedText() {
      const segment = findSelectedSegment();
      if (!segment || !("speechSynthesis" in window)) {
        return;
      }

      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(segment.text);
      utterance.lang = "he-IL";

      const match = window.speechSynthesis.getVoices().find(function (voice) {
        return voice.lang && voice.lang.toLowerCase().startsWith("he");
      });

      if (match) {
        utterance.voice = match;
      }

      window.speechSynthesis.speak(utterance);
      elements.selectedMeta.textContent = match
        ? "Playing a local Hebrew voice when available."
        : "Playing the default local voice. Use Google Translate if it sounds off.";
    }

    function downloadCurrentTranscript() {
      if (!state.working) {
        return;
      }

      const blob = new Blob([JSON.stringify(state.working, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "transcript-edited.json";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    }

    function resetTranscript() {
      if (!state.seed) {
        return;
      }

      localStorage.removeItem(STORAGE_KEY);
      state.working = deepClone(state.seed);
      state.currentPageIndex = 0;
      state.selectedSegmentId = null;
      renderStorageStatus();
      renderPage();
    }

    function addSegment(event) {
      event.preventDefault();

      const text = elements.addSegmentText.value.trim();
      if (!text || !state.working) {
        return;
      }

      const page = currentPage();
      const section = elements.addSegmentSection.value.trim() || "Custom additions";
      const segment = {
        id: makeSegmentId(page.page, page.segments.length),
        text: text,
        section: section,
        kind: text.indexOf(" ") >= 0 ? "phrase" : "word"
      };

      page.segments.push(segment);
      state.selectedSegmentId = segment.id;
      saveLocalState();
      elements.addSegmentText.value = "";
      elements.addSegmentSection.value = "";
      renderPage();
    }

    elements.prevPage.addEventListener("click", function () {
      changePage(-1);
    });

    elements.nextPage.addEventListener("click", function () {
      changePage(1);
    });

    elements.copyText.addEventListener("click", copySelectedText);
    elements.openTranslate.addEventListener("click", openSelectedInTranslate);
    elements.speakText.addEventListener("click", speakSelectedText);
    elements.exportTranscript.addEventListener("click", downloadCurrentTranscript);
    elements.resetTranscript.addEventListener("click", resetTranscript);
    elements.addSegmentForm.addEventListener("submit", addSegment);

    window.addEventListener("keydown", function (event) {
      const activeTag = document.activeElement && document.activeElement.tagName;
      if (activeTag === "INPUT" || activeTag === "TEXTAREA") {
        return;
      }

      if (event.key === "ArrowLeft") {
        changePage(-1);
      } else if (event.key === "ArrowRight") {
        changePage(1);
      }
    });

    loadTranscript();
  