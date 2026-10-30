"use strict";
/* The shared folder dialog (#folderDlg). App.pickFolder({ suggest: [paths], start: path, pick: async folder => {...} })
   opens it; "Use this folder" calls pick with the chosen path. Used by Clips and Shoot plan. */
(() => {
  let fd = null;                                       // the folder listing on show
  let onPick = null;                                   // what "Use this folder" does for whoever opened the dialog

  async function browse(path) {
    let r;
    try { r = await App.api(`/api/fs?path=${encodeURIComponent(path || "")}`); } catch (e) { App.toast(e.message, true); return; }
    fd = r; App.store.set("footage.browse", r.path);
    $("#fdPath").value = r.path;
    const list = $("#fdList"); list.innerHTML = "";
    if (r.path) list.append(el("div", { onclick: () => browse(r.parent) }, "⬑ up" + (r.parent ? "" : " (all drives)")));
    for (const d of r.dirs) list.append(el("div", { onclick: () => browse(d.path) }, "📁 " + d.name));
    if (!r.dirs.length) list.append(el("div", { class: "muted" }, "no sub-folders"));
    $("#fdInfo").textContent = r.path ? `${r.videos} video file${r.videos === 1 ? "" : "s"} directly in this folder` : "pick a drive";
    $("#fdPick").disabled = !r.path;
  }

  function openFolderDialog({ suggest = [], start = "", pick }) {
    onPick = pick;
    const sug = $("#fdSuggest"); sug.innerHTML = "";
    const list = [...suggest];
    sug.append(el("div", { class: "muted small" }, "Suggestions:"));
    for (const p of list) sug.append(el("button", { class: "ghost", onclick: () => browse(p) }, p));
    $("#folderDlg").showModal();
    browse(start || App.store.get("footage.browse", "") || list[0]);
  }
  App.pickFolder = openFolderDialog;

  $("#fdClose").onclick = () => $("#folderDlg").close();
  $("#fdGo").onclick = () => browse($("#fdPath").value.trim());
  $("#fdPath").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); browse($("#fdPath").value.trim()); } });
  $("#fdPick").onclick = async () => {
    try { $("#folderDlg").close(); if (onPick) await onPick(fd.path); }
    catch (e) { App.toast(e.message, true); }
  };
})();
