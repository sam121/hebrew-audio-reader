
    const state = {
      reader: null,
      currentPageIndex: 0,
      currentAudio: null,
      playbackToken: 0,
      activeLineId: null
    };

    const elements = {
      audioSummary: document.getElementById("audioSummary"),
      emptyState: document.getElementById("emptyState"),
      lineList: document.getElementById("lineList"),
      nextPage: document.getElementById("nextPage"),
      overlayLayer: document.getElementById("overlayLayer"),
      pageCounter: document.getElementById("pageCounter"),
      pageImage: document.getElementById("pageImage"),
      pageNotes: document.getElementById("pageNotes"),
      pageStatus: document.getElementById("pageStatus"),
      pageSubtitle: document.getElementById("pageSubtitle"),
      pageTitle: document.getElementById("pageTitle"),
      playbackStatus: document.getElementById("playbackStatus"),
      playPageEnglish: document.getElementById("playPageEnglish"),
      playPageHebrew: document.getElementById("playPageHebrew"),
      prevPage: document.getElementById("prevPage"),
      stopPlayback: document.getElementById("stopPlayback")
    };

    function currentPage() {
      return state.reader.pages[state.currentPageIndex];
    }

    function currentPageWordsById(page) {
      const byId = new Map();
      page.words.forEach(function (word) {
        byId.set(word.id, word);
      });
      return byId;
    }

    function setStatus(message, tone) {
      elements.playbackStatus.textContent = message;
      elements.audioSummary.textContent = tone || "";
    }

    function stopAudioOnly() {
      if (state.currentAudio) {
        state.currentAudio.pause();
        state.currentAudio.currentTime = 0;
        state.currentAudio = null;
      }
    }

    function stopPlayback(withMessage) {
      state.playbackToken += 1;
      stopAudioOnly();
      if (withMessage) {
        setStatus("Playback stopped.", "");
      }
    }

    function setActiveLine(lineId) {
      state.activeLineId = lineId || null;
      document.querySelectorAll(".line-card").forEach(function (card) {
        card.classList.toggle("active", card.dataset.lineId === state.activeLineId);
      });
      document.querySelectorAll(".line-overlay").forEach(function (overlay) {
        overlay.classList.toggle("active", overlay.dataset.lineId === state.activeLineId);
      });
    }

    function startPlayback(label, lineId) {
      stopPlayback(false);
      state.playbackToken += 1;
      setActiveLine(lineId || null);
      setStatus(label, "Playing");
      return state.playbackToken;
    }

    function playFile(url, token) {
      return new Promise(function (resolve, reject) {
        if (token !== state.playbackToken) {
          resolve(false);
          return;
        }

        const audio = new Audio(url);
        state.currentAudio = audio;

        audio.addEventListener("ended", function () {
          if (state.currentAudio === audio) {
            state.currentAudio = null;
          }
          resolve(true);
        });

        audio.addEventListener("error", function () {
          if (state.currentAudio === audio) {
            state.currentAudio = null;
          }
          reject(new Error("Audio failed to load: " + url));
        });

        const playResult = audio.play();
        if (playResult && typeof playResult.then === "function") {
          playResult.catch(function (error) {
            if (state.currentAudio === audio) {
              state.currentAudio = null;
            }
            reject(error);
          });
        }
      });
    }

    async function playSingle(url, label, lineId) {
      if (!url) {
        setStatus("Audio is not available for this item yet.", "Unavailable");
        return;
      }

      const token = startPlayback(label, lineId);
      try {
        await playFile(url, token);
        if (token === state.playbackToken) {
          setStatus(label + " finished.", "Ready");
        }
      } catch (error) {
        setStatus("Playback failed. Check the generated audio file.", "Error");
        console.error(error);
      }
    }

    async function playSequence(urls, label, lineId) {
      const sequence = urls.filter(Boolean);
      if (!sequence.length) {
        setStatus("Audio is not available for this item yet.", "Unavailable");
        return;
      }

      const token = startPlayback(label, lineId);
      try {
        for (const url of sequence) {
          if (token !== state.playbackToken) {
            return;
          }
          await playFile(url, token);
        }
        if (token === state.playbackToken) {
          setStatus(label + " finished.", "Ready");
        }
      } catch (error) {
        setStatus("Playback failed. Check the generated audio file.", "Error");
        console.error(error);
      }
    }

    function renderNotes(notes) {
      elements.pageNotes.replaceChildren();
      notes.forEach(function (note) {
        const item = document.createElement("li");
        item.textContent = note;
        elements.pageNotes.appendChild(item);
      });
    }

    function orderedLines(page) {
      return page.lines.slice().sort(function (a, b) {
        return a.order - b.order;
      });
    }

    function orderedSections(page) {
      if (page.sections && page.sections.length) {
        return page.sections.slice().sort(function (a, b) {
          return a.order - b.order;
        });
      }

      return [
        {
          id: "default",
          order: 1,
          title: "Transcript",
          description: "",
          hiddenHeading: true
        }
      ];
    }

    function buildLineDisplayText(line, wordsById) {
      return line.wordIds
        .map(function (wordId) {
          const word = wordsById.get(wordId);
          return word ? word.displayText : "";
        })
        .filter(Boolean)
        .join(" ");
    }

    function updateActiveFromEvent(lineId) {
      if (lineId) {
        setActiveLine(lineId);
      }
    }

    function renderOverlays(page) {
      elements.overlayLayer.replaceChildren();

      orderedLines(page).forEach(function (line) {
        if (!line.overlay) {
          return;
        }

        const overlay = document.createElement("div");
        overlay.className = "line-overlay";
        overlay.dataset.lineId = line.id;
        overlay.style.top = line.overlay.top + "%";
        overlay.style.left = line.overlay.left + "%";
        overlay.style.width = line.overlay.width + "%";
        overlay.style.height = line.overlay.height + "%";
        overlay.title = line.label;

        const number = document.createElement("span");
        number.className = "line-overlay-number";
        number.textContent = String(line.overlayNumber || line.order);
        overlay.appendChild(number);

        elements.overlayLayer.appendChild(overlay);
      });

      setActiveLine(state.activeLineId);
    }

    function renderLines(page) {
      const wordsById = currentPageWordsById(page);
      elements.lineList.replaceChildren();

      if (!page.lines.length) {
        elements.emptyState.classList.remove("hidden");
        return;
      }

      elements.emptyState.classList.add("hidden");

      orderedSections(page).forEach(function (section) {
        const sectionLines = orderedLines(page).filter(function (line) {
          return (line.sectionId || "default") === section.id;
        });
        const sectionIsSingleBlock = section.playbackMode === "single_block";

        if (!sectionLines.length) {
          return;
        }

        const sectionBlock = document.createElement("section");
        sectionBlock.className = "section-block";

        if (!section.hiddenHeading) {
          const sectionHeading = document.createElement("div");
          sectionHeading.className = "section-heading";

          const sectionHeadingRow = document.createElement("div");
          sectionHeadingRow.className = "section-heading-row";

          const sectionHeadingMain = document.createElement("div");

          const sectionLabel = document.createElement("p");
          sectionLabel.className = "panel-label";
          sectionLabel.textContent = section.title;
          sectionHeadingMain.appendChild(sectionLabel);

          if (section.description) {
            const sectionDescription = document.createElement("p");
            sectionDescription.className = "section-description";
            sectionDescription.textContent = section.description;
            sectionHeadingMain.appendChild(sectionDescription);
          }

          sectionHeadingRow.appendChild(sectionHeadingMain);

          if (sectionIsSingleBlock && section.audio && section.audio.mixed && section.audio.mixed.block) {
            const sectionActions = document.createElement("div");
            sectionActions.className = "section-actions";

            const playSection = document.createElement("button");
            playSection.type = "button";
            playSection.textContent = section.playbackLabel || "Play section";
            playSection.addEventListener("click", function () {
              playSingle(section.audio.mixed.block, section.title, null);
            });

            sectionActions.appendChild(playSection);
            sectionHeadingRow.appendChild(sectionActions);
          }

          sectionHeading.appendChild(sectionHeadingRow);

          sectionBlock.appendChild(sectionHeading);
        }

        if (sectionIsSingleBlock) {
          const combinedCard = document.createElement("section");
          combinedCard.className = "line-card";

          const sectionLineStack = document.createElement("div");
          sectionLineStack.className = "section-line-stack";

          sectionLines.forEach(function (line) {
            const lineItem = document.createElement("div");
            lineItem.className = "section-line-item";

            if (line.englishText) {
              const english = document.createElement("p");
              english.className = "line-english";
              english.textContent = line.englishText;
              lineItem.appendChild(english);
            }

            const hebrewText = buildLineDisplayText(line, wordsById);
            if (hebrewText) {
              const printedHebrew = document.createElement("p");
              printedHebrew.className = "printed-hebrew";
              printedHebrew.lang = "he";
              printedHebrew.dir = "rtl";
              printedHebrew.textContent = hebrewText;
              lineItem.appendChild(printedHebrew);
            }

            sectionLineStack.appendChild(lineItem);
          });

          combinedCard.appendChild(sectionLineStack);
          sectionBlock.appendChild(combinedCard);
          elements.lineList.appendChild(sectionBlock);
          return;
        }

        const sectionList = document.createElement("div");
        sectionList.className = "line-list";

        sectionLines.forEach(function (line) {
          const card = document.createElement("section");
          card.className = "line-card";
          card.dataset.lineId = line.id;

          card.addEventListener("mouseenter", function () {
            updateActiveFromEvent(line.id);
          });

          card.addEventListener("focusin", function () {
            updateActiveFromEvent(line.id);
          });

          card.addEventListener("click", function (event) {
            if (!event.target.closest("button")) {
              setActiveLine(line.id);
            }
          });

          const heading = document.createElement("div");
          heading.className = "line-heading";

          const headingMain = document.createElement("div");
          headingMain.className = "line-heading-main";

          const titleRow = document.createElement("div");
          titleRow.className = "line-title-row";

          const badge = document.createElement("span");
          badge.className = "line-badge";
          badge.textContent = line.badgeLabel || (line.overlayNumber ? "Line " + line.overlayNumber : "Line " + line.order);

          const label = document.createElement("p");
          label.className = "line-label";
          label.textContent = line.label;

          titleRow.appendChild(badge);
          titleRow.appendChild(label);
          headingMain.appendChild(titleRow);

          const helpText = line.overlay
            ? "Matches the active highlight on the scanned page."
            : (section.id === "intro" ? "Top-of-page transcription." : "");

          if (helpText) {
            const help = document.createElement("p");
            help.className = "line-help";
            help.textContent = helpText;
            headingMain.appendChild(help);
          }

          const hebrewText = buildLineDisplayText(line, wordsById);
          if (hebrewText) {
            const printedHebrew = document.createElement("p");
            printedHebrew.className = "printed-hebrew";
            printedHebrew.lang = "he";
            printedHebrew.dir = "rtl";
            printedHebrew.textContent = hebrewText;
            headingMain.appendChild(printedHebrew);
          }

          if (line.englishText) {
            const english = document.createElement("p");
            english.className = "line-english";
            english.textContent = line.englishText;
            headingMain.appendChild(english);
          }

          const actions = document.createElement("div");
          actions.className = "line-actions";

          if (line.hebrewAudioSequence && line.hebrewAudioSequence.length) {
            const playHebrew = document.createElement("button");
            playHebrew.type = "button";
            playHebrew.textContent = "Play Hebrew line";
            playHebrew.addEventListener("click", function () {
              playSequence(line.hebrewAudioSequence || [], line.label + " in Hebrew", line.id);
            });
            actions.appendChild(playHebrew);
          }

          if (line.audio && line.audio.en && line.audio.en.line) {
            const playEnglish = document.createElement("button");
            playEnglish.type = "button";
            playEnglish.className = "secondary";
            playEnglish.textContent = "Play printed English";
            playEnglish.addEventListener("click", function () {
              playSingle(line.audio.en.line, line.label + " in English", line.id);
            });
            actions.appendChild(playEnglish);
          }

          if (actions.childNodes.length) {
            heading.appendChild(headingMain);
            heading.appendChild(actions);
          } else {
            heading.appendChild(headingMain);
          }

          card.appendChild(heading);

          if (line.wordIds && line.wordIds.length) {
            const wordGrid = document.createElement("div");
            wordGrid.className = "word-grid";
            wordGrid.lang = "he";
            wordGrid.dir = "rtl";

            line.wordIds.forEach(function (wordId) {
              const word = wordsById.get(wordId);
              if (!word) {
                return;
              }

              const chip = document.createElement("button");
              chip.type = "button";
              chip.className = "word-chip";
              chip.textContent = word.displayText;
              chip.disabled = !word.audio || !word.audio.he || !word.audio.he.word;
              chip.title = word.spokenText;
              chip.addEventListener("click", function () {
                playSingle(word.audio.he.word, "Hebrew word: " + word.spokenText, line.id);
              });
              wordGrid.appendChild(chip);
            });

            card.appendChild(wordGrid);
          }

          sectionList.appendChild(card);
        });

        sectionBlock.appendChild(sectionList);
        elements.lineList.appendChild(sectionBlock);
      });

      setActiveLine(state.activeLineId);
    }

    function renderPage() {
      const page = currentPage();
      state.activeLineId = orderedLines(page)[0] ? orderedLines(page)[0].id : null;

      elements.pageTitle.textContent = page.title;
      elements.pageSubtitle.textContent = "Page " + page.page;
      elements.pageCounter.textContent = "Page " + (state.currentPageIndex + 1) + " of " + state.reader.pages.length;
      elements.pageStatus.textContent = page.status === "verified" ? "Verified" : "Pending transcription";
      elements.pageImage.src = page.image;
      elements.pageImage.alt = "Scanned book page " + page.page;
      elements.prevPage.disabled = state.currentPageIndex === 0;
      elements.nextPage.disabled = state.currentPageIndex === state.reader.pages.length - 1;
      elements.playPageHebrew.disabled = !(page.hebrewAudioSequence && page.hebrewAudioSequence.length);
      elements.playPageEnglish.disabled = !(page.audio && page.audio.en && page.audio.en.page);

      renderNotes(page.notes || []);
      renderLines(page);
      renderOverlays(page);

      setStatus(
        page.status === "verified"
          ? "Ready. Click a Hebrew word or use the numbered line controls."
          : "This page is visible, but it does not have verified audio yet.",
        page.status === "verified" ? "Ready" : "Pending"
      );
    }

    function movePage(delta) {
      const nextIndex = state.currentPageIndex + delta;
      if (nextIndex < 0 || nextIndex >= state.reader.pages.length) {
        return;
      }

      stopPlayback(false);
      state.currentPageIndex = nextIndex;
      renderPage();
    }

    async function loadReader() {
      try {
        const response = await fetch("./data/reader.json", { cache: "no-store" });
        if (!response.ok) {
          throw new Error("Reader data fetch failed: " + response.status);
        }

        state.reader = await response.json();
        renderPage();
      } catch (error) {
        setStatus("Site data could not be loaded. Run the build step first.", "Error");
        console.error(error);
      }
    }

    elements.prevPage.addEventListener("click", function () {
      movePage(-1);
    });

    elements.nextPage.addEventListener("click", function () {
      movePage(1);
    });

    elements.playPageHebrew.addEventListener("click", function () {
      const page = currentPage();
      playSequence(page.hebrewAudioSequence || [], "Page " + page.page + " in Hebrew", null);
    });

    elements.playPageEnglish.addEventListener("click", function () {
      const page = currentPage();
      playSingle(page.audio && page.audio.en ? page.audio.en.page : null, "Page " + page.page + " in English", null);
    });

    elements.stopPlayback.addEventListener("click", function () {
      stopPlayback(true);
    });

    window.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft") {
        movePage(-1);
      } else if (event.key === "ArrowRight") {
        movePage(1);
      }
    });

    loadReader();
  