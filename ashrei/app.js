const linesEl = document.querySelector("#lines");
const loopToggle = document.querySelector("#loopToggle");
let currentAudio = null;
let currentCard = null;

const playIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M8 5.14v13.72c0 .75.83 1.2 1.46.79l10.28-6.86a.95.95 0 0 0 0-1.58L9.46 4.35A.95.95 0 0 0 8 5.14Z"></path>
  </svg>`;

const pauseIcon = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path d="M7 5.5A1.5 1.5 0 0 1 8.5 4h1A1.5 1.5 0 0 1 11 5.5v13A1.5 1.5 0 0 1 9.5 20h-1A1.5 1.5 0 0 1 7 18.5v-13Zm6 0A1.5 1.5 0 0 1 14.5 4h1A1.5 1.5 0 0 1 17 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-1a1.5 1.5 0 0 1-1.5-1.5v-13Z"></path>
  </svg>`;

function resetCard(card) {
  if (!card) return;
  card.classList.remove("playing");
  const button = card.querySelector(".play");
  button.innerHTML = playIcon;
  button.setAttribute("aria-label", `Play line ${button.dataset.line}`);
}

window.ASHREI_LINES.forEach((line, index) => {
  const lineNumber = String(index + 1).padStart(2, "0");
  const card = document.createElement("section");
  card.className = "line-card";
  card.innerHTML = `
    <div class="controls">
      <span class="number">${lineNumber}</span>
      <button class="play" type="button" data-line="${lineNumber}" aria-label="Play line ${lineNumber}">
        ${playIcon}
      </button>
    </div>
    <div class="texts">
      <p class="hebrew" lang="he">${line.hebrew}</p>
      <p class="english">${line.english}</p>
    </div>
    <audio preload="metadata" src="audio/ashrei-${lineNumber}.m4a"></audio>
  `;
  linesEl.appendChild(card);
});

linesEl.addEventListener("click", async (event) => {
  const button = event.target.closest(".play");
  if (!button) return;

  const card = button.closest(".line-card");
  const audio = card.querySelector("audio");

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
