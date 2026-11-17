"use strict";

const el = id => document.getElementById(id);
let user = null;
let group = null;
let registering = false;

function notice(message, error = false) {
  el("notice").textContent = message;
  el("notice").classList.toggle("error", error);
}

async function api(path, method = "GET", body) {
  const response = await fetch("/api" + path, {
    method, cache: "no-store",
    headers: {"Content-Type": "application/json", "X-SmartFood": "1"},
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.detail || "Không thực hiện được yêu cầu.");
    error.status = response.status;
    throw error;
  }
  return data;
}

function show(id) {
  for (const key of ["account", "onboard", "home"]) el(key).hidden = key !== id;
  if (id !== "home") {
    group = null;
    resetCode();
    el("members").replaceChildren();
    el("codes").replaceChildren();
    el("home-name").textContent = "";
  }
  el("username").textContent = user?.username || "";
  el("logout").hidden = !user;
}

function resetCode() {
  el("code").value = "";
  el("new-code").hidden = true;
}

function button(text, action) {
  const control = document.createElement("button");
  control.textContent = text;
  control.onclick = () => run(control, action);
  return control;
}

function row(text) {
  const item = document.createElement("li");
  const label = document.createElement("span");
  label.textContent = text;
  item.append(label);
  return item;
}

function renderGroup() {
  const owner = group.owner_id === user.id;
  const path = "/households/" + group.id;
  el("home-name").textContent = group.name;
  el("members").replaceChildren();
  for (const member of group.members) {
    const item = row(member.username + (member.id === group.owner_id ? " · Chủ hộ" : " · Thành viên"));
    if (owner && member.id !== user.id) {
      item.append(button("Chuyển quyền", async () => {
        if (!confirm("Chuyển quyền chủ hộ cho " + member.username + "?")) return;
        await api(path + "/owner/" + member.id, "POST");
        await refresh();
        notice("Đã chuyển quyền chủ hộ.");
      }));
      item.append(button("Xóa khỏi hộ", async () => {
        if (!confirm("Xóa " + member.username + " khỏi hộ?")) return;
        await api(path + "/members/" + member.id, "DELETE");
        await refresh();
        notice("Đã xóa thành viên khỏi hộ.");
      }));
    }
    el("members").append(item);
  }
  el("leave").hidden = owner;
  el("invites").hidden = !owner;
  el("codes").replaceChildren();
  for (const invite of group.invitations || []) {
    const item = row("Mã #" + invite.id + " · hết hạn " + new Date(invite.expires_at * 1000).toLocaleString("vi-VN"));
    item.append(button("Thu hồi", async () => {
      await api(path + "/invitations/" + invite.id, "DELETE");
      await refresh();
      notice("Đã thu hồi mã mời.");
    }));
    el("codes").append(item);
  }
  show("home");
}

async function refresh() {
  resetCode();
  group = null;
  try {
    user = await api("/me");
  } catch (error) {
    if (error.status !== 401) throw error;
    user = null;
    show("account");
    return;
  }
  if (!user.household_id) {
    show("onboard");
    return;
  }
  group = await api("/households/" + user.household_id);
  renderGroup();
}

async function run(control, action) {
  control.disabled = true;
  notice("");
  try {
    await action();
  } catch (error) {
    if ([401, 403, 404, 409].includes(error.status)) {
      try { await refresh(); } catch { show(user ? "onboard" : "account"); }
    }
    notice(error.status ? error.message : "Không kết nối được dịch vụ. Hãy thử lại.", true);
  } finally {
    control.disabled = false;
  }
}

function mode(createAccount) {
  registering = createAccount;
  const label = registering ? "Tạo tài khoản" : "Đăng nhập";
  el("auth-title").textContent = el("auth-submit").textContent = label;
  el("mode").textContent = registering ? "Quay lại đăng nhập" : "Tạo tài khoản";
  el("auth-form").elements.password.autocomplete = registering ? "new-password" : "current-password";
}

el("mode").onclick = () => { mode(!registering); notice(""); };
for (const [id, submit] of [
  ["auth-form", async data => {
    if (registering) {
      await api("/auth/register", "POST", data);
      mode(false);
      el("auth-form").elements.password.value = "";
      notice("Đã tạo tài khoản. Hãy đăng nhập.");
    } else {
      await api("/auth/login", "POST", data);
      el("auth-form").reset();
      await refresh();
    }
  }],
  ["create-form", async data => { await api("/households", "POST", data); await refresh(); }],
  ["join-form", async data => { await api("/households/join", "POST", data); el("join-form").reset(); await refresh(); }]
]) {
  el(id).onsubmit = event => {
    event.preventDefault();
    const form = event.currentTarget;
    run(form.querySelector("button"), () => submit(Object.fromEntries(new FormData(form))));
  };
}
el("logout").onclick = () => run(el("logout"), async () => {
  await api("/auth/logout", "POST");
  el("create-form").reset();
  el("join-form").reset();
  await refresh();
});
el("refresh").onclick = () => run(el("refresh"), refresh);
el("issue").onclick = () => run(el("issue"), async () => {
  const result = await api("/households/" + group.id + "/invitations", "POST");
  await refresh();
  if (group?.owner_id === user?.id) {
    el("code").value = result.code;
    el("new-code").hidden = false;
  }
});
el("leave").onclick = () => run(el("leave"), async () => {
  if (!confirm("Rời hộ gia đình này?")) return;
  await api("/households/" + group.id + "/members/" + user.id, "DELETE");
  await refresh();
  notice("Đã rời hộ.");
});
window.addEventListener("pageshow", event => {
  if (event.persisted) run(el("refresh"), refresh);
});
run(el("refresh"), refresh);
