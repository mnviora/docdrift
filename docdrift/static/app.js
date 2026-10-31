// DocDrift front end. No libraries, no external requests.
// All user text is inserted with textContent, never as HTML.
(function () {
  "use strict";

  var MAX_FILE_BYTES = 1000000;
  var MAX_DIFF_CHARS = 100000;
  var MAX_DOC_CHARS = 100000;
  var MAX_DOCS = 10;

  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  var diffBox = $("diff");
  var docsBox = $("docs");
  var formError = $("form-error");
  var submitBtn = $("submit");
  var resultsSection = $("results");
  var resultsBody = $("results-body");
  var cardCounter = 0;
  var lastResult = null;
  var running = false;

  /* ---------------- status chip ---------------- */

  function refreshStatus() {
    return fetch("/api/status", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (s) {
        var state = s.ready ? "ready" : (s.ollama_reachable ? "no-model" : "no-ollama");
        var text = s.ready
          ? "Ollama running, " + s.model + " installed"
          : (s.ollama_reachable ? "Model " + s.model + " not installed" : "Ollama not reachable");
        $("status").setAttribute("data-state", state);
        $("status-text").textContent = text;
        var setup = $("setup");
        setup.hidden = !!s.ready;
        $("setup-message").textContent = s.ready ? "" : s.message;
      })
      .catch(function () {
        $("status").setAttribute("data-state", "no-ollama");
        $("status-text").textContent = "DocDrift server not responding";
      });
  }

  /* ---------------- document cards ---------------- */

  function docCards() { return docsBox.querySelectorAll(".doc-card"); }

  function updateRemoveButtons() {
    var cards = docCards();
    Array.prototype.forEach.call(cards, function (card) {
      card.querySelector(".doc-remove").hidden = cards.length < 2;
    });
    $("doc-add").disabled = cards.length >= MAX_DOCS;
  }

  function addDocCard(name, text) {
    if (docCards().length >= MAX_DOCS) {
      showFormError("You can check up to " + MAX_DOCS + " documents at a time.");
      return null;
    }
    cardCounter += 1;
    var n = cardCounter;
    var card = el("div", "doc-card");

    var head = el("div", "doc-head");
    var nameWrap = el("div", "doc-name");
    var nameLabel = el("label", null, "File name");
    nameLabel.setAttribute("for", "doc-name-" + n);
    var nameInput = el("input");
    nameInput.type = "text";
    nameInput.id = "doc-name-" + n;
    nameInput.value = name || "README.md";
    nameInput.autocomplete = "off";
    nameInput.spellcheck = false;
    nameWrap.appendChild(nameLabel);
    nameWrap.appendChild(nameInput);

    var remove = el("button", "btn quiet small doc-remove", "Remove");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove this document");
    remove.addEventListener("click", function () {
      card.remove();
      updateRemoveButtons();
    });
    head.appendChild(nameWrap);
    head.appendChild(remove);

    var textLabel = el("label", "visually-hidden", "Markdown text");
    textLabel.setAttribute("for", "doc-text-" + n);
    var area = el("textarea", "doc-text mono");
    area.id = "doc-text-" + n;
    area.rows = 9;
    area.spellcheck = false;
    area.value = text || "";

    card.appendChild(head);
    card.appendChild(textLabel);
    card.appendChild(area);
    docsBox.appendChild(card);
    updateRemoveButtons();
    return card;
  }

  function resetDocs(documents) {
    docsBox.textContent = "";
    if (documents && documents.length) {
      documents.forEach(function (d) { addDocCard(d.name, d.text); });
    } else {
      addDocCard("README.md", "");
    }
  }

  /* ---------------- messages ---------------- */

  function showFormError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }
  function clearFormError() {
    formError.textContent = "";
    formError.hidden = true;
  }

  /* ---------------- file upload (read in the browser, never stored) ---------------- */

  function readTextFile(file, allowedExtensions, label) {
    var lower = file.name.toLowerCase();
    var ok = allowedExtensions.some(function (ext) { return lower.endsWith(ext); });
    if (!ok) {
      return Promise.reject(new Error(
        "'" + file.name + "' is not a " + label + " file. Use " + allowedExtensions.join(", ") + "."));
    }
    if (file.size > MAX_FILE_BYTES) {
      return Promise.reject(new Error(
        "'" + file.name + "' is too large (" + Math.round(file.size / 1000) + " KB). The limit is " +
        Math.round(MAX_FILE_BYTES / 1000) + " KB."));
    }
    return file.text().then(function (text) {
      if (text.indexOf("\u0000") !== -1) {
        throw new Error("'" + file.name + "' looks like a binary file. Use plain text.");
      }
      return text;
    });
  }

  $("diff-upload").addEventListener("click", function () { $("diff-file").click(); });
  $("diff-file").addEventListener("change", function (event) {
    var file = event.target.files[0];
    event.target.value = "";
    if (!file) return;
    clearFormError();
    readTextFile(file, [".diff", ".patch", ".txt"], "diff or patch")
      .then(function (text) { diffBox.value = text; })
      .catch(function (err) { showFormError(err.message); });
  });

  $("docs-upload").addEventListener("click", function () { $("docs-file").click(); });
  $("docs-file").addEventListener("change", function (event) {
    var files = Array.prototype.slice.call(event.target.files);
    event.target.value = "";
    if (!files.length) return;
    clearFormError();
    Promise.all(files.map(function (file) {
      return readTextFile(file, [".md", ".markdown"], "Markdown")
        .then(function (text) { return { name: file.name, text: text }; });
    })).then(function (loaded) {
      // Replace a lone empty card instead of leaving a blank one behind.
      var cards = docCards();
      if (cards.length === 1 && !cards[0].querySelector("textarea").value.trim()) {
        docsBox.textContent = "";
      }
      loaded.forEach(function (d) { addDocCard(d.name, d.text); });
    }).catch(function (err) { showFormError(err.message); });
  });

  $("doc-add").addEventListener("click", function () {
    var card = addDocCard("notes.md", "");
    if (card) card.querySelector("input").focus();
  });

  /* ---------------- sample and clear ---------------- */

  function loadSample() {
    clearFormError();
    return fetch("/api/sample", { cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (sample) {
        diffBox.value = sample.diff;
        resetDocs(sample.documents);
        resultsSection.hidden = true;
        resultsBody.textContent = "";
        lastResult = null;
        $("checker").scrollIntoView();
        submitBtn.focus();
      })
      .catch(function () {
        showFormError("Could not load the sample. Is DocDrift still running in your terminal?");
      });
  }
  $("try-sample").addEventListener("click", loadSample);
  $("sample-again").addEventListener("click", loadSample);

  $("clear").addEventListener("click", function () {
    diffBox.value = "";
    resetDocs(null);
    clearFormError();
    resultsSection.hidden = true;
    resultsBody.textContent = "";
    lastResult = null;
    diffBox.focus();
  });

  $("recheck").addEventListener("click", refreshStatus);

  /* ---------------- submit ---------------- */

  function collect() {
    var documents = [];
    Array.prototype.forEach.call(docCards(), function (card) {
      documents.push({
        name: card.querySelector("input").value,
        text: card.querySelector("textarea").value
      });
    });
    return { diff: diffBox.value, documents: documents };
  }

  function validateLocally(payload) {
    if (!payload.diff.trim()) {
      diffBox.focus();
      return "Add a code diff first: paste the output of `git diff`, upload a .diff or .patch file, or load the sample.";
    }
    if (payload.diff.length > MAX_DIFF_CHARS) {
      diffBox.focus();
      return "The diff is too large (" + payload.diff.length.toLocaleString() + " characters). The limit is " +
        MAX_DIFF_CHARS.toLocaleString() + ". Try a smaller change.";
    }
    var withText = payload.documents.filter(function (d) { return d.text.trim(); });
    if (!withText.length) {
      docsBox.querySelector("textarea").focus();
      return "Add documentation to check: paste Markdown, upload .md files, or load the sample.";
    }
    for (var i = 0; i < withText.length; i++) {
      if (withText[i].text.length > MAX_DOC_CHARS) {
        return "'" + withText[i].name + "' is too large. The limit per document is " +
          MAX_DOC_CHARS.toLocaleString() + " characters.";
      }
    }
    return null;
  }

  function showWorking() {
    resultsBody.textContent = "";
    var box = el("div", "working");
    box.appendChild(el("div", "spinner"));
    var text = el("div");
    text.appendChild(el("p", null, "qwen3.5:4b is reading your diff and documentation on this computer."));
    var timer = el("p", "note", "A small local model can take a minute or two, especially on the first run. Elapsed: 0s");
    timer.setAttribute("aria-hidden", "true");
    text.appendChild(timer);
    box.appendChild(text);
    resultsBody.appendChild(box);
    resultsSection.hidden = false;
    resultsSection.scrollIntoView();

    var started = Date.now();
    var id = setInterval(function () {
      var s = Math.round((Date.now() - started) / 1000);
      timer.textContent = "A small local model can take a minute or two, especially on the first run. Elapsed: " + s + "s";
    }, 1000);
    return function stop() { clearInterval(id); };
  }

  function setRunning(isRunning) {
    running = isRunning;
    submitBtn.disabled = isRunning;
    submitBtn.textContent = isRunning ? "Checking…" : "Check documentation";
    resultsSection.setAttribute("aria-busy", isRunning ? "true" : "false");
  }

  $("form").addEventListener("submit", function (event) {
    event.preventDefault();
    if (running) return;
    clearFormError();
    var payload = collect();
    var problem = validateLocally(payload);
    if (problem) { showFormError(problem); return; }

    setRunning(true);
    var stopTimer = showWorking();

    fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        return response.json().then(
          function (body) { return { status: response.status, body: body }; },
          function () { return { status: response.status, body: null }; }
        );
      })
      .then(function (r) {
        stopTimer();
        setRunning(false);
        if (r.body && r.body.ok) {
          lastResult = r.body;
          renderResult(r.body);
        } else if (r.body && r.body.error) {
          renderError(r.body.error);
        } else {
          renderError({ code: "unexpected", message: "The server sent an unexpected reply (HTTP " + r.status + ")." });
        }
      })
      .catch(function () {
        stopTimer();
        setRunning(false);
        renderError({
          code: "no_server",
          message: "The DocDrift server is not responding. Check that it is still running in your terminal."
        });
      });
  });

  /* ---------------- rendering results ---------------- */

  var STATUS_LABEL = { possible_drift: "Possible documentation drift", uncertain: "Uncertain" };

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }

  function evidenceBlock(text) {
    var pre = el("pre", "evidence mono");
    pre.setAttribute("tabindex", "0");
    pre.setAttribute("aria-label", "Changed code");
    String(text).split("\n").forEach(function (line) {
      var cls = null;
      if (line.charAt(0) === "-" && line.indexOf("---") !== 0) cls = "d-del";
      else if (line.charAt(0) === "+" && line.indexOf("+++") !== 0) cls = "d-add";
      var row = el("span", cls, line === "" ? " " : line);
      pre.appendChild(row);
    });
    return pre;
  }

  function findingCard(f) {
    var status = f.status === "possible_drift" ? "possible_drift" : "uncertain";
    var card = el("article", "finding");
    card.setAttribute("data-status", status);

    var head = el("div", "finding-head");
    head.appendChild(el("h3", "finding-label", STATUS_LABEL[status]));
    var where = f.document_file || "unknown file";
    if (typeof f.line_number === "number") where += ", line " + f.line_number;
    head.appendChild(el("span", "finding-where", where));
    card.appendChild(head);

    if (f.quoted_text) {
      card.appendChild(el("p", "field-name", "The documentation says"));
      card.appendChild(el("blockquote", null, f.quoted_text));
    }
    card.appendChild(el("p", "field-name", "Changed code that supports this"));
    if (f.code_evidence) {
      card.appendChild(evidenceBlock(f.code_evidence));
    } else {
      card.appendChild(el("p", "why", "No matching line in the diff was found, so this is only a possible concern."));
    }
    if (f.explanation) {
      card.appendChild(el("p", "field-name", "Why it may be outdated"));
      card.appendChild(el("p", "why", f.explanation));
    }
    return card;
  }

  function renderResult(result) {
    resultsBody.textContent = "";
    var s = result.summary;

    var verdict = el("div", "verdict");
    verdict.setAttribute("data-kind", result.verdict);
    if (result.verdict === "possible_drift") {
      verdict.appendChild(el("h3", null, "Possible documentation drift"));
      verdict.appendChild(el("p", null,
        plural(s.possible_drift, "possible drift", "possible drifts") +
        (s.uncertain ? " and " + plural(s.uncertain, "uncertain finding", "uncertain findings") : "") +
        " in the supplied files. Check each one below before you merge."));
    } else if (result.verdict === "uncertain") {
      verdict.appendChild(el("h3", null, "Uncertain"));
      verdict.appendChild(el("p", null,
        plural(s.uncertain, "sentence", "sentences") +
        " might be affected, but the diff does not prove it. Review them yourself."));
    } else {
      verdict.appendChild(el("h3", null, "No likely drift found in the supplied files"));
      verdict.appendChild(el("p", null,
        "DocDrift checked only the diff and documentation you gave it. That does not prove your other docs are up to date."));
    }
    resultsBody.appendChild(verdict);

    if (result.warnings && result.warnings.length) {
      var notes = el("ul", "notes");
      result.warnings.forEach(function (w) { notes.appendChild(el("li", null, w)); });
      resultsBody.appendChild(notes);
    }

    var downloads = el("div", "downloads");
    var md = el("button", "btn quiet", "Download Markdown");
    md.type = "button";
    md.addEventListener("click", function () {
      download("docdrift-report.md", result.markdown, "text/markdown;charset=utf-8");
    });
    var js = el("button", "btn quiet", "Download JSON");
    js.type = "button";
    js.addEventListener("click", function () {
      var data = {
        tool: "DocDrift",
        model: result.model,
        verdict: result.verdict,
        summary: result.summary,
        findings: result.findings,
        warnings: result.warnings
      };
      download("docdrift-report.json", JSON.stringify(data, null, 2) + "\n", "application/json;charset=utf-8");
    });
    downloads.appendChild(md);
    downloads.appendChild(js);
    resultsBody.appendChild(downloads);

    result.findings.forEach(function (f) { resultsBody.appendChild(findingCard(f)); });

    resultsSection.hidden = false;
    resultsSection.focus();
    resultsSection.scrollIntoView();
  }

  function renderError(error) {
    resultsBody.textContent = "";
    var titles = {
      ollama_unavailable: "Ollama is not running",
      model_missing: "The model is not installed",
      model_error: "The model gave an unusable answer",
      busy: "A check is already running",
      too_large: "Too much text",
      no_server: "DocDrift is not responding"
    };
    var box = el("div", "error-box");
    box.setAttribute("role", "alert");
    box.appendChild(el("h3", null, titles[error.code] || "The check could not run"));
    box.appendChild(el("p", null, error.message));
    if (error.fix) box.appendChild(el("p", null, "What to do: " + error.fix));
    resultsBody.appendChild(box);
    resultsSection.hidden = false;
    resultsSection.scrollIntoView();
    if (error.code === "ollama_unavailable" || error.code === "model_missing") refreshStatus();
  }

  function download(filename, text, type) {
    var blob = new Blob([text], { type: type });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  /* ---------------- start ---------------- */

  resetDocs(null);
  refreshStatus();
  window.addEventListener("focus", refreshStatus);
})();
