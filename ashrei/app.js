const linesEl = document.querySelector("#lines");
const tabsEl = document.querySelector("#tabs");
const loopToggle = document.querySelector("#loopToggle");
const prayerTitle = document.querySelector("#prayerTitle");
const sourceNote = document.querySelector("#sourceNote");
let currentAudio = null;
let currentCard = null;
const attentionPrefix = "hebrew-prayer-attention";

const playIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M8 5.14v13.72c0 .75.83 1.2 1.46.79l10.28-6.86a.95.95 0 0 0 0-1.58L9.46 4.35A.95.95 0 0 0 8 5.14Z"></path>
  </svg>`;

const pauseIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7 5.5A1.5 1.5 0 0 1 8.5 4h1A1.5 1.5 0 0 1 11 5.5v13A1.5 1.5 0 0 1 9.5 20h-1A1.5 1.5 0 0 1 7 18.5v-13Zm6 0A1.5 1.5 0 0 1 14.5 4h1A1.5 1.5 0 0 1 17 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-1a1.5 1.5 0 0 1-1.5-1.5v-13Z"></path>
  </svg>`;

const flagIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M6 21a1 1 0 0 1-1-1V5.8c0-.48.34-.9.81-.98l.93-.16a8.6 8.6 0 0 1 5.17.71 6.62 6.62 0 0 0 4.03.5l1.87-.34A1 1 0 0 1 19 6.52v8.14c0 .48-.34.9-.81.98l-1.9.34a8.62 8.62 0 0 1-5.17-.71 6.6 6.6 0 0 0-4.03-.5L7 14.79V20a1 1 0 0 1-1 1Z"></path>
  </svg>`;

function resetCard(card) {
  if (!card) return;
  card.classList.remove("playing");
  const button = card.querySelector(".play");
  button.innerHTML = playIcon;
  button.setAttribute("aria-label", `Play line ${button.dataset.line}`);
}

function attentionKey(prayerId, lineNumber) {
  return `${attentionPrefix}:${prayerId}:${lineNumber}`;
}

function isAttentionLine(prayerId, lineNumber) {
  return localStorage.getItem(attentionKey(prayerId, lineNumber)) === "1";
}

function setAttentionLine(card, prayerId, lineNumber, isMarked) {
  const button = card.querySelector(".attention");
  card.classList.toggle("needs-attention", isMarked);
  button.classList.toggle("active", isMarked);
  button.setAttribute("aria-pressed", String(isMarked));
  button.setAttribute(
    "aria-label",
    `${isMarked ? "Unflag" : "Flag"} line ${lineNumber} for extra attention`
  );
  if (isMarked) {
    localStorage.setItem(attentionKey(prayerId, lineNumber), "1");
  } else {
    localStorage.removeItem(attentionKey(prayerId, lineNumber));
  }
}

function stopCurrentAudio() {
  if (!currentAudio) return;
  currentAudio.pause();
  currentAudio.currentTime = 0;
  resetCard(currentCard);
  currentAudio = null;
  currentCard = null;
}

function renderTabs(activeId) {
  tabsEl.innerHTML = "";
  window.PRAYERS.forEach((prayer) => {
    const tab = document.createElement("button");
    tab.className = `tab${prayer.id === activeId ? " active" : ""}`;
    tab.type = "button";
    tab.textContent = prayer.title;
    tab.setAttribute("aria-current", prayer.id === activeId ? "page" : "false");
    tab.addEventListener("click", () => renderPrayer(prayer.id));
    tabsEl.appendChild(tab);
  });
}

function renderPrayer(prayerId) {
  stopCurrentAudio();
  const prayer = window.PRAYERS.find((item) => item.id === prayerId) || window.PRAYERS[0];
  renderTabs(prayer.id);
  prayerTitle.textContent = prayer.title;
  sourceNote.textContent = prayer.note;
  linesEl.innerHTML = "";

  prayer.lines.forEach((line, index) => {
    const lineNumber = String(index + 1).padStart(2, "0");
    const hasAudio = Boolean(prayer.audioPattern);
    const audioSrc = hasAudio ? prayer.audioPattern.replace("{line}", lineNumber) : "";
    const needsAttention = isAttentionLine(prayer.id, lineNumber);
    const card = document.createElement("section");
    card.className = `line-card${needsAttention ? " needs-attention" : ""}`;
    card.innerHTML = `
      <div class="controls">
        <span class="number">${lineNumber}</span>
        <button class="play" type="button" data-line="${lineNumber}" aria-label="Play line ${lineNumber}" ${hasAudio ? "" : "disabled"}>
          ${playIcon}
        </button>
        <button class="attention${needsAttention ? " active" : ""}" type="button" data-prayer="${prayer.id}" data-line="${lineNumber}" aria-pressed="${needsAttention}" aria-label="${needsAttention ? "Unflag" : "Flag"} line ${lineNumber} for extra attention">
          ${flagIcon}
        </button>
      </div>
      <div class="texts">
        <p class="hebrew" lang="he">${line.hebrew}</p>
        ${line.english ? `<p class="english">${line.english}</p>` : ""}
        ${hasAudio ? "" : `<p class="pending">Awaiting timestamp for this line.</p>`}
      </div>
      ${hasAudio ? `<audio preload="metadata" src="${audioSrc}"></audio>` : ""}
    `;
    linesEl.appendChild(card);
  });
}

linesEl.addEventListener("click", async (event) => {
  const attentionButton = event.target.closest(".attention");
  if (attentionButton) {
    const card = attentionButton.closest(".line-card");
    const prayerId = attentionButton.dataset.prayer;
    const lineNumber = attentionButton.dataset.line;
    const isMarked = !card.classList.contains("needs-attention");
    setAttentionLine(card, prayerId, lineNumber, isMarked);
    return;
  }

  const button = event.target.closest(".play");
  if (!button) return;

  const card = button.closest(".line-card");
  const audio = card.querySelector("audio");
  if (!audio) return;

  if (currentAudio && currentAudio !== audio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    resetCard(currentCard);
  }

  currentAudio = audio;
  currentCard = card;
  audio.loop = loopToggle.checked;

  if (audio.paused) {
    card.classList.add("playing");
    button.innerHTML = pauseIcon;
    button.setAttribute("aria-label", `Pause line ${button.dataset.line}`);
    await audio.play();
  } else {
    audio.pause();
    resetCard(card);
  }
});

linesEl.addEventListener("ended", (event) => {
  if (event.target instanceof HTMLAudioElement && !event.target.loop) {
    resetCard(event.target.closest(".line-card"));
  }
}, true);

loopToggle.addEventListener("change", () => {
  if (currentAudio) currentAudio.loop = loopToggle.checked;
});

renderPrayer(window.PRAYERS[0].id);
