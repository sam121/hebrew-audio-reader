const DIRS = {
  up: { x: 0, y: -1 },
  down: { x: 0, y: 1 },
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
};

export function createGameState({ rows = 20, cols = 20, rng = Math.random } = {}) {
  const midX = Math.floor(cols / 2);
  const midY = Math.floor(rows / 2);
  const snake = [
    { x: midX, y: midY },
    { x: midX - 1, y: midY },
    { x: midX - 2, y: midY },
  ];

  const food = placeFood({ rows, cols, snake, rng });

  return {
    rows,
    cols,
    snake,
    direction: "right",
    pendingDirection: "right",
    food,
    score: 0,
    gameOver: false,
    paused: false,
    rng,
  };
}

export function setDirection(state, nextDir) {
  if (!DIRS[nextDir]) return state;
  if (areOpposite(state.direction, nextDir)) return state;
  return { ...state, pendingDirection: nextDir };
}

export function togglePause(state) {
  if (state.gameOver) return state;
  return { ...state, paused: !state.paused };
}

export function step(state) {
  if (state.gameOver || state.paused) return state;

  const direction = state.pendingDirection;
  const nextHead = getNextHead(state.snake[0], direction);

  if (isOutOfBounds(nextHead, state.rows, state.cols)) {
    return { ...state, gameOver: true };
  }

  const hitBody = state.snake.some(
    (segment, index) => index !== state.snake.length - 1 && samePos(segment, nextHead)
  );
  if (hitBody) {
    return { ...state, gameOver: true };
  }

  const ateFood = samePos(nextHead, state.food);
  const newSnake = [nextHead, ...state.snake];
  if (!ateFood) {
    newSnake.pop();
  }

  const food = ateFood
    ? placeFood({ rows: state.rows, cols: state.cols, snake: newSnake, rng: state.rng })
    : state.food;

  const gameOver = food === null;

  return {
    ...state,
    direction,
    snake: newSnake,
    food,
    score: state.score + (ateFood ? 1 : 0),
    gameOver,
  };
}

export function placeFood({ rows, cols, snake, rng }) {
  const free = [];
  for (let y = 0; y < rows; y += 1) {
    for (let x = 0; x < cols; x += 1) {
      if (!snake.some((segment) => segment.x === x && segment.y === y)) {
        free.push({ x, y });
      }
    }
  }

  if (free.length === 0) return null;
  const idx = Math.floor(rng() * free.length);
  return free[idx];
}

function getNextHead(head, direction) {
  const move = DIRS[direction] || DIRS.right;
  return { x: head.x + move.x, y: head.y + move.y };
}

function isOutOfBounds(pos, rows, cols) {
  return pos.x < 0 || pos.y < 0 || pos.x >= cols || pos.y >= rows;
}

function areOpposite(a, b) {
  return (
    (a === "up" && b === "down") ||
    (a === "down" && b === "up") ||
    (a === "left" && b === "right") ||
    (a === "right" && b === "left")
  );
}

function samePos(a, b) {
  return a.x === b.x && a.y === b.y;
}
