const typeSelect = document.querySelector("[data-action-type]");
const commandField = document.querySelector("[data-command-field]");
const scriptField = document.querySelector("[data-script-field]");
const inputsToggle = document.querySelector("[data-inputs-toggle]");
const inputsField = document.querySelector("[data-inputs-field]");

function syncActionFields() {
  if (!typeSelect || !commandField || !scriptField) return;
  const isScript = typeSelect.value === "ps1";
  commandField.hidden = isScript;
  scriptField.hidden = !isScript;
}

typeSelect?.addEventListener("change", syncActionFields);
syncActionFields();

function syncInputsField() {
  if (!inputsToggle || !inputsField) return;
  inputsField.hidden = !inputsToggle.checked;
}

inputsToggle?.addEventListener("change", syncInputsField);
syncInputsField();

document.querySelectorAll("[data-help-toggle]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = document.getElementById(button.dataset.helpToggle);
    if (!target) return;
    target.hidden = !target.hidden;
  });
});

const aiGenerateForm = document.querySelector("[data-ai-generate-form]");
aiGenerateForm?.addEventListener("submit", () => {
  const thinking = aiGenerateForm.querySelector("[data-ai-thinking]");
  const submit = aiGenerateForm.querySelector("[data-ai-submit]");
  if (thinking) thinking.hidden = false;
  if (submit) {
    submit.disabled = true;
    submit.textContent = "Generating...";
  }
});

const liveOutput = document.querySelector("[data-live-output-title]")?.closest("#live-output");
const liveOutputTitle = document.querySelector("[data-live-output-title]");
const liveOutputStatus = document.querySelector("[data-live-output-status]");
const liveOutputRunning = document.querySelector("[data-live-output-running]");
const liveOutputClose = document.querySelector("[data-live-output-close]");
const liveOutputStdout = document.querySelector("[data-live-output-stdout]");
const liveOutputStderr = document.querySelector("[data-live-output-stderr]");
const liveOutputStderrWrap = document.querySelector("[data-live-output-stderr-wrap]");

document.querySelectorAll("[data-live-run-form]").forEach((form) => {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button[type='submit']");
    const actionName = form.dataset.actionName || "Action";
    setLiveOutputRunning(actionName, button);

    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ inputs: collectRunInputs(actionName) }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Action failed to run.");
      setLiveOutputComplete(payload);
    } catch (error) {
      setLiveOutputComplete({
        action_name: actionName,
        status: "failed",
        exit_code: null,
        stdout: "",
        stderr: error.message || String(error),
        duration_ms: null,
      });
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Run";
      }
    }
  });
});

liveOutputClose?.addEventListener("click", () => {
  if (liveOutput) liveOutput.hidden = true;
});

function setLiveOutputRunning(actionName, button) {
  if (!liveOutput) return;
  liveOutput.hidden = false;
  if (liveOutputClose) liveOutputClose.hidden = true;
  if (liveOutputRunning) liveOutputRunning.hidden = false;
  if (liveOutputTitle) liveOutputTitle.textContent = actionName;
  if (liveOutputStatus) liveOutputStatus.textContent = "Running...";
  if (liveOutputStdout) liveOutputStdout.textContent = "";
  if (liveOutputStderr) liveOutputStderr.textContent = "";
  if (liveOutputStderrWrap) liveOutputStderrWrap.hidden = true;
  if (button) {
    button.disabled = true;
    button.textContent = "Running...";
  }
  liveOutput.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function collectRunInputs(actionName) {
  const inputForm = Array.from(document.querySelectorAll("[data-live-run-inputs]")).find((candidate) => candidate.dataset.liveRunInputs === actionName);
  if (!inputForm) return {};
  const values = {};
  new FormData(inputForm).forEach((value, key) => {
    values[key.replace(/^input_/, "")] = value;
  });
  return values;
}

function setLiveOutputComplete(payload) {
  if (!liveOutput) return;
  const exitCode = payload.exit_code === null || payload.exit_code === undefined ? "" : ` - Exit ${payload.exit_code}`;
  const duration = payload.duration_ms === null || payload.duration_ms === undefined ? "" : ` - ${payload.duration_ms} ms`;
  if (liveOutputRunning) liveOutputRunning.hidden = true;
  if (liveOutputClose) liveOutputClose.hidden = false;
  if (liveOutputTitle) liveOutputTitle.textContent = payload.action_name || "Action";
  if (liveOutputStatus) liveOutputStatus.textContent = `${payload.status || "completed"}${exitCode}${duration}`;
  if (liveOutputStdout) liveOutputStdout.textContent = payload.stdout || "(no output)";
  if (liveOutputStderr) liveOutputStderr.textContent = payload.stderr || "";
  if (liveOutputStderrWrap) liveOutputStderrWrap.hidden = !payload.stderr;
}
