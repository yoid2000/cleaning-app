"use strict";

// The server applies these rules too; forms work without JavaScript.
const jobsForm = document.getElementById("jobs-form");
if (jobsForm) {
  const boxes = [...jobsForm.querySelectorAll('input[name="jobs"]')];
  const summary = document.getElementById("selection-summary");
  const update = () => {
    const selected = boxes.filter(box => box.checked && !box.disabled);
    const units = selected.reduce((total, box) => total + Number(box.dataset.units), 0);
    summary.textContent = `${selected.length} ${selected.length === 1 ? "job" : "jobs"} selected · ${units} work units`;
  };
  boxes.forEach(box => box.addEventListener("change", () => {
    const matching = task => boxes.find(other => other.dataset.room === box.dataset.room && other.dataset.task === task);
    if (box.dataset.task === "mop" && box.checked) matching("vacuum").checked = true;
    if (box.dataset.task === "vacuum" && !box.checked) matching("mop").checked = false;
    update();
  }));
  update();
}
