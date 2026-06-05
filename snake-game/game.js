import { createGameState, setDirection, step, togglePause } from "./logic.js";

const boardEl = document.getElementById("board");
const scoreEl = document.getElementById("score");
const restartBtn = document.getElementById("restart");
const overlayEl = document.getElementById("overlay");
const overlayTitle = document.getElementById("overlay-title");

const TICK_MS = 140;

let state = createGameState();
let lastTime = 0;
let acc = 0;

const cells = buildGrid(state.rows, state.cols);
render(state);

function buildGrid(rows, cols) {
  const list = [];
  boardEl.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  boardEl.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
  boardEl.innerHTML = "";
  for (let i = 0; i < rows * cols; i += 1) {
    const cell = document.createElement("div");
    cell.className = "cell";
    boardEl.appendChild(cell);
    list.push(cell);
  }
  return list;
}

function render(next) {
  for (const cell of cells) {
    cell.className = "cell";
  }

  next.snake.forEach((segment, index) => {
    const idx = segment.y * next.cols + segment.x;
    const cell = cells[idx];
    if (!cell) return;
    cell.classList.add("snake");
    if (index === 0) cell.classList.add("head");
  });

  if (next.food) {
    const foodIdx = next.food.y * next.cols + next.food.x;
    cells[foodIdx]?.classList.add("food");
  }

  scoreEl.textContent = String(next.score);

  if (next.gameOver) {
    overlayTitle.textContent = "Game Over";
    overlayEl.hidden = false;
  } else if (next.paused) {
    overlayTitle.textContent = "Paused";
    overlayEl.hidden = false;
  } else {
    overlayEl.hidden = true;
  }
}

function loop(ts) {
  if (!lastTime) lastTime = ts;
  const delta = ts - lastTime;
  lastTime = ts;
  acc += delta;

  while (acc >= TICK_MS) {
    acc -= TICK_MS;
    state = step(state);
  }

  render(state);
  requestAnimationFrame(loop);
}

requestAnimationFrame(loop);

window.addEventListener("keydown", (event) => {
  const key = event.key.toLowerCase();
  if (["arrowup", "arrowdown", "arrowleft", "arrowright", "w", "a", "s", "d", " "].includes(key)) {
    event.preventDefault();
  }

  if (key === " " || key === "spacebar") {
    state = togglePause(state);
    return;
  }

  if (key === "arrowup" || key === "w") state = setDirection(state, "up");
  if (key === "arrowdown" || key === "s") state = setDirection(state, "down");
  if (key === "arrowleft" || key === "a") state = setDirection(state, "left");
  if (key === "arrowright" || key === "d") state = setDirection(state, "right");
});

restartBtn.addEventListener("click", () => {
  state = createGameState();
  acc = 0;
  lastTime = 0;
  render(state);
});

for (const btn of document.querySelectorAll(".ctrl")) {
  btn.addEventListener("click", () => {
    state = setDirection(state, btn.dataset.dir);
  });
}
