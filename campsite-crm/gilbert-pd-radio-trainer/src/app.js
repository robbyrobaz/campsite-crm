const STORAGE_CODES = "gilbert_radio_codes_v1";
const STORAGE_STATS = "gilbert_radio_stats_v1";
const OFFICIAL_DATA_URL = "./data/gilbert-official-codes.json";
const STARTER_DATA_URL = "./data/starter-codes.json";

const state = {
  codes: [],
  stats: { correct: 0, attempts: 0, bestStreak: 0, currentStreak: 0 },
  quiz: null,
  speed: { active: false, timeLeft: 60, score: 0, timerId: null, current: null },
  flash: { current: null }
};

const els = {
  tabs: [...document.querySelectorAll(".tab-btn")],
  tabContent: [...document.querySelectorAll(".tab-content")],
  statCorrect: document.getElementById("stat-correct"),
  statStreak: document.getElementById("stat-streak"),
  statAccuracy: document.getElementById("stat-accuracy"),
  searchInput: document.getElementById("search-input"),
  teachGrid: document.getElementById("teach-grid"),
  teachCount: document.getElementById("teach-count"),
  quizCode: document.getElementById("quiz-code"),
  quizOptions: document.getElementById("quiz-options"),
  quizFeedback: document.getElementById("quiz-feedback"),
  quizNext: document.getElementById("quiz-next"),
  speedTime: document.getElementById("speed-time"),
  speedScore: document.getElementById("speed-score"),
  speedPlay: document.getElementById("speed-play"),
  speedCode: document.getElementById("speed-code"),
  speedOptions: document.getElementById("speed-options"),
  speedFeedback: document.getElementById("speed-feedback"),
  speedStart: document.getElementById("speed-start"),
  flashCard: document.getElementById("flash-card"),
  flashCode: document.getElementById("flash-code"),
  flashMeaning: document.getElementById("flash-meaning"),
  flashNext: document.getElementById("flash-next"),
  flashShow: document.getElementById("flash-show"),
  exportBtn: document.getElementById("export-btn"),
  importInput: document.getElementById("import-input"),
  addForm: document.getElementById("add-form"),
  newCode: document.getElementById("new-code"),
  newMeaning: document.getElementById("new-meaning"),
  newCategory: document.getElementById("new-category")
};

init();

async function init() {
  await loadCodes();
  loadStats();
  bindEvents();
  renderStats();
  renderTeach();
  buildQuizQuestion();
  buildFlashcard();
}

async function loadCodes() {
  const cached = localStorage.getItem(STORAGE_CODES);
  if (cached) {
    state.codes = JSON.parse(cached);
    return;
  }

  let loaded = false;

  try {
    const res = await fetch(OFFICIAL_DATA_URL);
    if (!res.ok) {
      throw new Error(`Official dataset request failed (${res.status})`);
    }
    const payload = await res.json();
    const normalized = normalizeImportedCodes(payload);
    if (!normalized.length) {
      throw new Error("Official dataset missing or empty");
    }
    state.codes = normalized;
    loaded = true;
  } catch (err) {
    console.warn("Official dataset load failed, falling back to starter list", err);
  }

  if (!loaded) {
    try {
      const res = await fetch(STARTER_DATA_URL);
      if (!res.ok) {
        throw new Error(`Starter dataset request failed (${res.status})`);
      }
      state.codes = await res.json();
      loaded = true;
    } catch (fallbackErr) {
      console.error("Starter dataset fallback failed", fallbackErr);
    }
  }

  if (!loaded) {
    state.codes = [];
  }

  persistCodes();
}

function loadStats() {
  const cached = localStorage.getItem(STORAGE_STATS);
  if (cached) state.stats = JSON.parse(cached);
}

function persistCodes() {
  localStorage.setItem(STORAGE_CODES, JSON.stringify(state.codes));
}

function persistStats() {
  localStorage.setItem(STORAGE_STATS, JSON.stringify(state.stats));
}

function bindEvents() {
  els.tabs.forEach((btn) => {
    btn.addEventListener("click", () => {
      els.tabs.forEach((t) => t.classList.remove("active"));
      btn.classList.add("active");
      const id = btn.dataset.tab;
      els.tabContent.forEach((content) => {
        content.classList.toggle("active", content.id === `tab-${id}`);
      });
    });
  });

  els.searchInput.addEventListener("input", renderTeach);
  els.quizNext.addEventListener("click", buildQuizQuestion);

  els.speedStart.addEventListener("click", startSpeedRound);
  els.exportBtn.addEventListener("click", exportCodes);
  els.importInput.addEventListener("change", importCodes);
  els.addForm.addEventListener("submit", addCode);
  els.flashShow.addEventListener("click", toggleFlashMeaning);
  els.flashNext.addEventListener("click", () => buildFlashcard());
}

function renderStats() {
  const accuracy = state.stats.attempts
    ? Math.round((state.stats.correct / state.stats.attempts) * 100)
    : 0;
  els.statCorrect.textContent = String(state.stats.correct);
  els.statStreak.textContent = String(state.stats.bestStreak);
  els.statAccuracy.textContent = `${accuracy}%`;
}

function renderTeach() {
  const term = els.searchInput.value.trim().toLowerCase();
  const filtered = state.codes.filter((item) => {
    const blob = `${item.code} ${item.meaning} ${item.category}`.toLowerCase();
    return blob.includes(term);
  });

  els.teachCount.textContent = `${filtered.length} codes`;
  els.teachGrid.innerHTML = filtered
    .map(
      (item) => `
      <article class="card">
        <h3>${escapeHtml(item.code)}</h3>
        <p>${escapeHtml(item.meaning)}</p>
        <span class="badge">${escapeHtml(item.category)}</span>
      </article>
    `
    )
    .join("");
}

function buildQuizQuestion() {
  if (state.codes.length < 4) return;

  const correct = pickRandom(state.codes);
  const pool = state.codes.filter((item) => item.code !== correct.code);
  const wrongs = shuffle(pool).slice(0, 3).map((item) => item.meaning);
  const options = shuffle([correct.meaning, ...wrongs]);

  state.quiz = { code: correct.code, meaning: correct.meaning, answered: false };
  els.quizCode.textContent = correct.code;
  els.quizFeedback.textContent = "";
  els.quizNext.disabled = true;

  els.quizOptions.innerHTML = options
    .map((opt) => `<button class="option" data-value="${escapeAttr(opt)}">${escapeHtml(opt)}</button>`)
    .join("");

  [...els.quizOptions.querySelectorAll(".option")].forEach((btn) => {
    btn.addEventListener("click", () => gradeAnswer(btn, btn.dataset.value));
  });
}

function gradeAnswer(btn, value) {
  if (!state.quiz || state.quiz.answered) return;
  state.quiz.answered = true;

  const isCorrect = value === state.quiz.meaning;
  state.stats.attempts += 1;

  if (isCorrect) {
    state.stats.correct += 1;
    state.stats.currentStreak += 1;
    state.stats.bestStreak = Math.max(state.stats.bestStreak, state.stats.currentStreak);
    els.quizFeedback.textContent = "Correct. Nice work.";
    btn.classList.add("correct");
  } else {
    state.stats.currentStreak = 0;
    els.quizFeedback.textContent = `Not quite. Correct answer: ${state.quiz.meaning}`;
    btn.classList.add("wrong");
    [...els.quizOptions.querySelectorAll(".option")].forEach((opt) => {
      if (opt.dataset.value === state.quiz.meaning) opt.classList.add("correct");
    });
  }

  [...els.quizOptions.querySelectorAll(".option")].forEach((opt) => {
    opt.disabled = true;
  });

  persistStats();
  renderStats();
  els.quizNext.disabled = false;
}

function startSpeedRound() {
  if (state.codes.length < 4) return;
  if (state.speed.timerId) clearInterval(state.speed.timerId);

  state.speed.active = true;
  state.speed.timeLeft = 60;
  state.speed.score = 0;
  els.speedPlay.classList.remove("hidden");
  els.speedStart.disabled = true;
  els.speedFeedback.textContent = "";
  updateSpeedMeta();
  buildSpeedQuestion();

  state.speed.timerId = setInterval(() => {
    state.speed.timeLeft -= 1;
    updateSpeedMeta();
    if (state.speed.timeLeft <= 0) {
      endSpeedRound();
    }
  }, 1000);
}

function buildSpeedQuestion() {
  const correct = pickRandom(state.codes);
  const pool = state.codes.filter((item) => item.code !== correct.code);
  const wrongs = shuffle(pool).slice(0, 3).map((item) => item.meaning);
  const options = shuffle([correct.meaning, ...wrongs]);

  state.speed.current = { code: correct.code, meaning: correct.meaning };
  els.speedCode.textContent = correct.code;
  els.speedOptions.innerHTML = options
    .map((opt) => `<button class="option" data-value="${escapeAttr(opt)}">${escapeHtml(opt)}</button>`)
    .join("");

  [...els.speedOptions.querySelectorAll(".option")].forEach((btn) => {
    btn.addEventListener("click", () => gradeSpeed(btn.dataset.value));
  });
}

function gradeSpeed(value) {
  if (!state.speed.active) return;

  if (value === state.speed.current.meaning) {
    state.speed.score += 1;
    state.stats.correct += 1;
    state.stats.attempts += 1;
    els.speedFeedback.textContent = "Correct";
  } else {
    state.stats.attempts += 1;
    els.speedFeedback.textContent = `Nope: ${state.speed.current.meaning}`;
  }

  persistStats();
  renderStats();
  updateSpeedMeta();
  buildSpeedQuestion();
}

function endSpeedRound() {
  state.speed.active = false;
  clearInterval(state.speed.timerId);
  state.speed.timerId = null;
  els.speedFeedback.textContent = `Time. Final score: ${state.speed.score}`;
  els.speedStart.disabled = false;
}

function updateSpeedMeta() {
  els.speedTime.textContent = String(state.speed.timeLeft);
  els.speedScore.textContent = String(state.speed.score);
}

function buildFlashcard() {
  if (!state.codes.length) {
    els.flashCode.textContent = "--";
    els.flashMeaning.textContent = "Load some codes to practice.";
    els.flashMeaning.classList.remove("hidden");
    return;
  }

  const card = pickRandom(state.codes);
  state.flash.current = card;
  els.flashCode.textContent = card.code;
  els.flashMeaning.textContent = card.meaning;
  els.flashMeaning.classList.add("hidden");
  els.flashShow.textContent = "Show Meaning";
}

function toggleFlashMeaning() {
  if (!state.flash.current) return;
  const visible = !els.flashMeaning.classList.contains("hidden");
  els.flashMeaning.classList.toggle("hidden", visible);
  els.flashShow.textContent = visible ? "Show Meaning" : "Hide Meaning";
}

function exportCodes() {
  const blob = new Blob([JSON.stringify(state.codes, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "gilbert-radio-codes.json";
  a.click();
  URL.revokeObjectURL(url);
}

async function importCodes(event) {
  const file = event.target.files[0];
  if (!file) return;

  const text = await file.text();
  const parsed = JSON.parse(text);
  const normalized = normalizeImportedCodes(parsed);

  if (!normalized.length) {
    alert("Invalid file. JSON must be an array of {code, meaning, category} objects or the Gilbert PD dataset payload.");
    return;
  }

  state.codes = normalized;
  persistCodes();
  renderTeach();
  buildQuizQuestion();
  alert(`Code list imported (${normalized.length} entries).`);
}

function addCode(event) {
  event.preventDefault();
  const code = els.newCode.value.trim();
  const meaning = els.newMeaning.value.trim();
  const category = els.newCategory.value.trim();
  if (!code || !meaning || !category) return;

  state.codes.push({ code, meaning, category });
  persistCodes();
  renderTeach();
  buildQuizQuestion();
  els.addForm.reset();
}

function normalizeImportedCodes(payload) {
  if (!payload) return [];

  if (Array.isArray(payload)) {
    return payload
      .map((item) => normalizeEntry(item))
      .filter((item) => item !== null);
  }

  if (Array.isArray(payload.series)) {
    return payload.series
      .flatMap((series) => {
        const category = series.name || "Imported";
        return (series.codes || [])
          .map((code) => normalizeEntry({ ...code, category }, category))
          .filter((item) => item !== null);
      })
      .filter((item) => item !== null);
  }

  return [];
}

function normalizeEntry(entry, fallbackCategory = "Imported") {
  if (!entry || !entry.code || !entry.meaning) return null;
  return {
    code: String(entry.code).trim(),
    meaning: String(entry.meaning).trim(),
    category: entry.category ? String(entry.category).trim() : fallbackCategory
  };
}

function pickRandom(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function shuffle(list) {
  const arr = [...list];
  for (let i = arr.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("`", "&#96;");
}
