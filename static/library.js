(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const state = {
    heroes: [],
    schools: [],
    schoolMap: new Map(),
    cards: [],
    rules: null,
    selected: null,
    tab: "heroes",
  };

  const TIER_RANK = { S: 5, A: 4, B: 3, C: 2, D: 1, "?": 0 };
  const DIFFICULTY = { 1: "简单", 2: "中等", 3: "偏难" };
  let artErrors = 0;

  function showAlert(message) {
    const el = $("#libAlert");
    if (!el) return;
    el.hidden = false;
    el.textContent = message;
  }

  function onArtError() {
    artErrors += 1;
    if (artErrors === 1) {
      showAlert("英雄图片加载失败。请确认是通过 http://127.0.0.1:8777/library 打开的，并检查 /api/art-check 的返回；如果显示 0/60，说明还在跑旧版服务，关掉旧控制台后重新运行 启动助手.bat。");
    }
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function portraitUrl(path) {
    if (!path) return "";
    if (path.startsWith("data:") || path.startsWith("http") || path.startsWith("/")) return path;
    return "/" + path;
  }

  function schoolTag(school) {
    const color = school.color || "#9aa4b2";
    return '<span class="school-tag"><i class="dot" style="background:' + escapeHtml(color) + '"></i>' + escapeHtml(school.name || school) + "</span>";
  }

  function rarityClass(rarity) {
    return Number(rarity) >= 3 ? "r3" : Number(rarity) === 2 ? "r2" : "r1";
  }

  async function init() {
    if (window.location.protocol === "file:") {
      showAlert("不要直接双击 library.html。请先运行 启动助手.bat，然后打开 http://127.0.0.1:8777/library。");
      return;
    }
    try {
      const [heroData, cardData, ruleData] = await Promise.all([
        fetch("/api/heroes").then((r) => r.json()),
        fetch("/api/cards").then((r) => r.json()),
        fetch("/api/rules").then((r) => r.json()),
      ]);
      state.heroes = heroData.heroes || [];
      state.schools = heroData.schools || [];
      state.schoolMap = new Map(state.schools.map((s) => [s.id, s]));
      state.cards = cardData.cards || [];
      state.rules = ruleData.rules || null;
      $("#libHeroCount").textContent = state.heroes.length;
      $("#libCardCount").textContent = state.cards.length;
      $("#tierNote").textContent = (heroData.meta && heroData.meta.tier_note) || "";
      const meta = heroData.meta || {};
      if (!meta.version) {
        showAlert("当前服务端还是旧版本（没有图片素材字段）。请关掉旧的助手/网页控制台窗口，重新运行 启动助手.bat，再按 Ctrl+F5。");
      } else if (Number(meta.art || 0) < state.heroes.length) {
        showAlert("图片素材没有完整加载：" + Number(meta.art || 0) + "/" + state.heroes.length + "。请确认 data/art 目录存在，然后重启助手并强制刷新页面。");
      }
      fillSchoolSelects();
      bindEvents();
      renderHeroes();
      renderCards();
      renderRules();
      const hash = (window.location.hash || "#heroes").replace("#", "");
      showView(["heroes", "cards", "rules"].includes(hash) ? hash : "heroes", false);
      if (state.heroes.length) {
        selectHero(state.heroes[0].name);
      }
    } catch (err) {
      $("#heroGrid").innerHTML = '<p class="tiny-note">数据加载失败：' + escapeHtml(err.message) + "</p>";
    }
  }

  function fillSchoolSelects() {
    const options = state.schools
      .map((s) => '<option value="' + escapeHtml(s.id) + '">' + escapeHtml(s.name) + "</option>")
      .join("");
    $("#heroSchool").insertAdjacentHTML("beforeend", options);
    $("#cardSchool").insertAdjacentHTML("beforeend", options);
  }

  function bindEvents() {
    $("#heroSearch").addEventListener("input", renderHeroes);
    $("#heroSchool").addEventListener("change", renderHeroes);
    $("#heroSort").addEventListener("change", renderHeroes);
    $("#cardSearch").addEventListener("input", renderCards);
    $("#cardSchool").addEventListener("change", renderCards);
    $("#cardRarity").addEventListener("change", renderCards);
    $$("[data-nav]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const tab = link.dataset.nav;
        showView(tab, true);
      });
    });
    window.addEventListener("hashchange", () => {
      const tab = (window.location.hash || "#heroes").replace("#", "");
      if (["heroes", "cards", "rules"].includes(tab)) showView(tab, false);
    });
  }

  function showView(tab, updateHash) {
    state.tab = tab;
    ["heroes", "cards", "rules"].forEach((name) => {
      $("#" + name + "View").hidden = name !== tab;
    });
    $$("[data-nav]").forEach((link) => {
      link.classList.toggle("primary", link.dataset.nav === tab);
    });
    if (updateHash && window.location.hash !== "#" + tab) {
      window.location.hash = tab;
    }
  }

  function heroMatches(hero) {
    const query = ($("#heroSearch").value || "").trim().toLowerCase();
    if (query) {
      const haystack = (hero.name + " " + (hero.aliases || []).join(" ") + " " + (hero.role || "")).toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    const school = $("#heroSchool").value;
    if (school && !(hero.schools || []).some((s) => s.id === school)) return false;
    return true;
  }

  function renderHeroes() {
    const sort = $("#heroSort").value;
    const heroes = state.heroes.filter(heroMatches).sort((a, b) => {
      if (sort === "name") return a.name.localeCompare(b.name, "zh-CN");
      if (sort === "cards") return (b.core_cards || []).length - (a.core_cards || []).length;
      if (sort === "tier") {
        const tierDiff = (TIER_RANK[b.tier] || 0) - (TIER_RANK[a.tier] || 0);
        if (tierDiff) return tierDiff;
      }
      return Number(b.power || 0) - Number(a.power || 0);
    });
    $("#heroResultCount").textContent = heroes.length + " / " + state.heroes.length + " 位英雄";
    $("#heroGrid").innerHTML = heroes.map((hero) => {
      const portrait = portraitUrl(hero.art || hero.portrait);
      const schools = (hero.schools || []).slice(0, 3).map(schoolTag).join("");
      return (
        '<article class="hero-tile' + (state.selected === hero.name ? " active" : "") + '" data-name="' + escapeHtml(hero.name) + '">' +
          (portrait ? '<img class="ht-portrait" src="' + portrait + '" alt="">' : '<div class="ht-fallback">' + escapeHtml(hero.name.slice(0, 1)) + "</div>") +
          '<div class="ht-main">' +
            '<div class="ht-name">' + escapeHtml(hero.name) + '<span class="tier">' + escapeHtml(hero.tier || "?") + "</span></div>" +
            '<div class="ht-role">' + escapeHtml(hero.role || "") + "</div>" +
            '<div class="ht-power">' + escapeHtml(hero.power || 0) + "<small>强度</small></div>" +
            '<div class="ht-schools">' + schools + "</div>" +
          "</div>" +
        "</article>"
      );
    }).join("");
    $$(".hero-tile").forEach((tile) => {
      tile.addEventListener("click", () => selectHero(tile.dataset.name));
    });
    $$(".hero-tile img").forEach((img) => img.addEventListener("error", onArtError));
  }

  function selectHero(name) {
    const hero = state.heroes.find((h) => h.name === name);
    if (!hero) return;
    state.selected = name;
    $$(".hero-tile").forEach((tile) => tile.classList.toggle("active", tile.dataset.name === name));
    renderDetail(hero);
  }

  function statCell(label, value, suffix) {
    return '<div class="stat-cell"><span>' + escapeHtml(label) + "</span><b>" + escapeHtml(value) + (suffix || "") + "</b></div>";
  }

  function renderDetail(hero) {
    const portrait = portraitUrl(hero.art || hero.portrait);
    const schoolRows = (hero.schools || []).map((s) => {
      const width = Math.max(4, Math.round((s.weight || 0) * 100));
      return (
        '<div class="affinity-row">' +
          '<img src="' + escapeHtml(s.icon || "") + '" alt="">' +
          '<span class="an">' + escapeHtml(s.name) + "</span>" +
          '<span class="bar"><i class="fill" style="width:' + width + '%"></i></span>' +
          '<span class="av">' + Math.round((s.weight || 0) * 100) + "%</span>" +
        "</div>"
      );
    }).join("");
    const core = (hero.core_cards || []).map((c) => (
      '<div class="core-item">' +
        '<div class="core-head"><span class="core-name">' + escapeHtml(c.name) + "</span>" +
          '<span class="core-rarity ' + rarityClass(c.rarity) + '">' + escapeHtml(c.rarity_name || "") + "</span>" +
          '<span class="core-reason">' + escapeHtml(c.reason || "") + "</span></div>" +
        '<div class="core-schools">' + (c.factions || []).map((f) => '<span class="school-tag">' + escapeHtml(f) + "</span>").join("") + "</div>" +
        '<div class="core-desc">' + escapeHtml(c.desc || "") + "</div>" +
      "</div>"
    )).join("");
    const counters = (hero.weak_to || []).length
      ? hero.weak_to.map((s) => '<span class="school-tag">' + escapeHtml(s.name) + "</span>").join("")
      : '<span class="tiny-note">暂无明确克制记录</span>';
    const stats = hero.stats || {};
    const detail = $("#heroDetail");
    detail.innerHTML =
      '<div class="detail-head">' +
        (portrait ? '<img class="detail-portrait" src="' + portrait + '" alt="">' : "") +
        '<div style="min-width:0;flex:1">' +
          '<h2 class="detail-name">' + escapeHtml(hero.name) +
            '<span class="school-tag" style="color:var(--gold);border-color:rgba(231,189,97,.35)">' + escapeHtml(hero.tier || "?") + " 级</span>" +
          "</h2>" +
          '<div class="detail-role">' + escapeHtml(hero.role || "") + " · 难度 " + escapeHtml(DIFFICULTY[hero.difficulty] || "中等") + "</div>" +
          '<div class="detail-meta">' +
            (hero.has_guide ? '<span class="school-tag" style="color:#b8f2df;border-color:rgba(103,216,178,.3)">有攻略</span>' : '<span class="school-tag">暂无攻略</span>') +
            '<span class="school-tag">' + (hero.core_cards || []).length + " 张核心卡</span>" +
          "</div>" +
        "</div>" +
        '<div class="detail-power"><b>' + escapeHtml(hero.power || 0) + "</b><span>POWER</span></div>" +
      "</div>" +
      '<p class="detail-summary">' + escapeHtml(hero.summary || "") + "</p>" +
      '<div class="detail-section"><div class="detail-title">基础面板</div><div class="stat-grid">' +
        statCell("生命", stats.hp) + statCell("攻击", stats.attack) + statCell("攻速", stats.attack_speed, "/s") +
        statCell("回能", stats.energy_regen, "/s") + statCell("闪避", stats.dodge, "%") + statCell("暴击", stats.crit, "%") +
      "</div></div>" +
      '<div class="detail-section"><div class="detail-title">天赋 / 大招</div>' +
        '<div class="skill-box skill-box-icon">' +
          (hero.talent_icon ? '<img class="skill-icon" src="' + portraitUrl(hero.talent_icon) + '" alt="">' : "") +
          '<div><b>天赋</b><p>' + escapeHtml(hero.talent || "—") + "</p></div></div>" +
        '<div class="skill-box skill-box-icon">' +
          (hero.ultimate_icon ? '<img class="skill-icon" src="' + portraitUrl(hero.ultimate_icon) + '" alt="">' : "") +
          '<div><b>大招</b><p>' + escapeHtml(hero.ultimate || "—") + "</p></div></div>" +
      "</div>" +
      '<div class="detail-section"><div class="detail-title">推荐流派</div>' + (schoolRows || '<p class="tiny-note">暂无流派数据</p>') + "</div>" +
      '<div class="detail-section"><div class="detail-title">核心卡 · 优先围绕主系抓取</div><div class="core-list">' + (core || '<p class="tiny-note">暂无匹配卡牌</p>') + "</div></div>" +
      '<div class="detail-section"><div class="detail-title">怕的体系</div><div class="counter-list">' + counters + "</div></div>" +
      '<div class="detail-section"><div class="detail-title">攻略</div><div id="guideSlot"><p class="tiny-note">加载攻略…</p></div></div>';
    $$("#heroDetail img").forEach((img) => img.addEventListener("error", onArtError));
    loadGuide(hero);
  }

  async function loadGuide(hero) {
    const slot = $("#guideSlot");
    if (!hero.has_guide) {
      slot.innerHTML = '<p class="tiny-note">暂无完整攻略。上面的天赋、大招与核心卡就是当前可用的结构化资料。</p>';
      return;
    }
    try {
      const data = await fetch("/api/guide?hero=" + encodeURIComponent(hero.name)).then((r) => r.json());
      if (state.selected !== hero.name) return;
      const content = (data.content || "").replace(/^---[\s\S]*?---\s*/, "");
      slot.innerHTML = '<details class="guide-box"><summary>查看《' + escapeHtml(hero.guide_title || hero.name) + "》</summary><pre>" + escapeHtml(content) + "</pre></details>";
    } catch (err) {
      slot.innerHTML = '<p class="tiny-note">攻略加载失败</p>';
    }
  }

  function cardMatches(card) {
    const query = ($("#cardSearch").value || "").trim().toLowerCase();
    if (query) {
      const text = (card.name + " " + (card.desc || "") + " " + (card.factions || []).join(" ")).toLowerCase();
      if (!text.includes(query)) return false;
    }
    const school = $("#cardSchool").value;
    if (school && !(card.faction_ids || []).includes(school)) return false;
    const rarity = $("#cardRarity").value;
    if (rarity && String(card.rarity) !== rarity) return false;
    return true;
  }

  function renderCards() {
    const cards = state.cards.filter(cardMatches).sort((a, b) => {
      if (Number(b.rarity) !== Number(a.rarity)) return Number(b.rarity) - Number(a.rarity);
      return String(a.factions?.[0] || "").localeCompare(String(b.factions?.[0] || ""), "zh-CN") || Number(a.id) - Number(b.id);
    });
    $("#cardResultCount").textContent = cards.length + " / " + state.cards.length + " 张卡牌";
    $("#cardGrid").innerHTML = cards.map((card) => (
      '<article class="lib-card">' +
        '<div class="lib-card-head"><span class="lib-card-name">' + escapeHtml(card.name) + "</span>" +
          '<span class="rarity-tag ' + rarityClass(card.rarity) + '">' + escapeHtml(card.rarity_name) + "</span>" +
          '<span class="lib-card-id">#' + escapeHtml(card.id) + "</span></div>" +
        '<div class="lib-card-schools">' + (card.factions || []).map((f) => '<span class="school-tag">' + escapeHtml(f) + "</span>").join("") + "</div>" +
        '<div class="lib-card-desc">' + escapeHtml(card.desc || "") + "</div>" +
        '<div class="lib-card-foot"><span>卡池数量 ' + escapeHtml(card.pool || 0) + "</span><span>" + (card.faction_ids || []).length + " 流派</span></div>" +
      "</article>"
    )).join("") || '<p class="tiny-note">没有匹配的卡牌</p>';
  }

  function renderRules() {
    if (!state.rules) return;
    const attributes = (state.rules.attributes || []).map((item) => "<li><b>" + escapeHtml(item.name) + "</b>：" + escapeHtml(item.text) + "</li>").join("");
    const economy = (state.rules.economy || []).map((item) => "<li>" + escapeHtml(item) + "</li>").join("");
    const schoolCards = state.schools.map((school) => {
      const text = (state.rules.schools || {})[school.id] || school.mechanics || "";
      return '<div class="rule-school"><b>' + escapeHtml(school.name) + "</b><p>" + escapeHtml(text) + "</p></div>";
    }).join("");
    $("#rulesContent").innerHTML =
      '<div class="rule-card"><h3>基础属性</h3><ul>' + attributes + "</ul></div>" +
      '<div class="rule-card"><h3>经济与利息</h3><ul>' + economy + "</ul></div>" +
      '<div class="rule-card"><h3>13 流派机制</h3>' + schoolCards + "</div>";
  }

  init();
})();
