let me = null;
let authMode = "login";
let providers = {};

const $ = (id) => document.getElementById(id);

async function readJson(url, opt) {
  const res = await fetch(url, opt);
  const data = await res.json().catch(() => ({}));
  return data;
}

function paint() {
  const btn = $("accountBtn");
  const enter = $("enterBtn");
  const hello = $("landHello");
  if (me) {
    const left = me.quota?.left;
    btn.textContent = "退出";
    enter.textContent = "进入盯盘看板";
    hello.textContent = left == null ? me.name : `${me.name} · 今日余 ${left}`;
  } else {
    btn.textContent = "登录";
    enter.textContent = "登录后进入看板";
    hello.textContent = "";
  }
  document.querySelectorAll(".oauth-btn").forEach((el) => {
    const ready = providers[el.dataset.provider]?.ready;
    el.disabled = !ready;
    el.title = ready ? "" : "社交密钥未配置，请用邮箱";
  });
}

function openAuth() {
  $("authMask").classList.remove("hidden");
  $("authErr").textContent = "";
}

function closeAuth() {
  $("authMask").classList.add("hidden");
}

function goBoard() {
  window.location.href = "/board";
}

async function refreshMe() {
  const data = await readJson("/api/auth/me");
  me = data.user ? { ...data.user, quota: data.quota } : null;
  providers = data.providers || {};
  paint();
}

async function submitAuth(event) {
  event.preventDefault();
  $("authErr").textContent = "";
  const payload = {
    email: $("authEmail").value.trim(),
    password: $("authPass").value,
    name: $("authName").value.trim(),
  };
  const path = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
  const data = await readJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!data.ok) {
    $("authErr").textContent = data.error || "没有登录成功";
    return;
  }
  goBoard();
}

async function signOut() {
  await readJson("/api/auth/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).catch(() => {});
  me = null;
  paint();
}

function boot() {
  const need = new URLSearchParams(location.search).get("need");
  if (need) {
    $("needNote").textContent = "看板需要登录后才能进入。";
    openAuth();
  }
  $("enterBtn").addEventListener("click", () => (me ? goBoard() : openAuth()));
  $("accountBtn").addEventListener("click", () => (me ? signOut() : openAuth()));
  $("authClose").addEventListener("click", closeAuth);
  $("authMask").addEventListener("click", (event) => {
    if (event.target === $("authMask")) closeAuth();
  });
  $("authForm").addEventListener("submit", submitAuth);
  $("authToggle").addEventListener("click", () => {
    authMode = authMode === "login" ? "register" : "login";
    $("authTitle").textContent = authMode === "login" ? "登录赤盘" : "注册赤盘";
    $("authSubmit").textContent = authMode === "login" ? "登录并进入看板" : "注册并进入看板";
    $("authToggle").textContent = authMode === "login" ? "没有账号，去注册" : "已有账号，去登录";
    $("authName").classList.toggle("hidden", authMode === "login");
    $("authNameLabel").classList.toggle("hidden", authMode === "login");
  });
  document.querySelectorAll(".oauth-btn").forEach((el) => {
    el.addEventListener("click", () => {
      if (el.disabled) {
        $("authErr").textContent = "社交密钥未配置，请用邮箱";
        return;
      }
      window.location.href = "/api/auth/start/" + el.dataset.provider;
    });
  });
  refreshMe();
}

boot();
