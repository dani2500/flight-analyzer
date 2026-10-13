$(function () {
  const sessionId = String(Date.now()) + Math.random().toString(36).slice(2);
  const $chat = $("#chat"), $input = $("#input");
  const LABELS = Object.assign({ code: "Code", airport: "Airport", city: "City" }, METRICS);
  let rec = null, handsFree = false, speaking = false, utterance = null;
  // Push-to-talk: recording runs until the mic is clicked again, then the text is sent.
  let ptt = false, pttSend = false, pttBase = "";

  function fmt(v) {
    if (v === null || v === undefined) return "n/a";
    return typeof v === "number" ? v.toLocaleString("en-US") : v;
  }

  function table(rows, highlight) {
    if (!rows.length) return $("<p>").text("No airports to show.");
    const cols = Object.keys(rows[0]);
    const $t = $("<table>");
    const $head = $("<tr>").appendTo($("<thead>").appendTo($t));
    cols.forEach(c => $("<th>").text(LABELS[c] || c.replace(/_/g, " ")).toggleClass("hl", c === highlight).appendTo($head));
    const $body = $("<tbody>").appendTo($t);
    rows.forEach(r => {
      const $tr = $("<tr>").appendTo($body);
      cols.forEach(c => $("<td>").text(fmt(r[c])).toggleClass("hl", c === highlight).appendTo($tr));
    });
    return $("<div class='scroll'>").append($t);
  }

  function list(title, items) {
    const $ul = $("<ul>");
    items.forEach(i => $("<li>").text(i).appendTo($ul));
    return $("<div>").append($("<h4>").text(title), $ul);
  }

  // Render one tool result: these are the deterministic numbers, shown as returned.
  function evidence(step) {
    const r = step.result, $e = $("<div class='evidence'>");
    if (r.error) return $e.append($("<p class='error'>").text(r.error));
    $e.append($("<h3>").text(r.title));
    if (r.rank) $e.append($("<p>").text("Rank among peers: " + r.rank));
    if (r.breakdown) $e.append(table(r.breakdown));
    $e.append(table(r.rows, r.ranked_by));
    if (r.head_to_head && r.head_to_head.length) $e.append(list("Head to head (highest first)", r.head_to_head));
    $.each(r.reasons || {}, (code, items) => { if (items.length) $e.append(list("Why · " + code, items)); });
    $.each(r.live_faa_status || {}, (code, s) => {
      const text = typeof s === "string" ? s : s.map(x =>
        Object.entries(x).map(([k, v]) => k + ": " + v).join(", ")).join(" | ");
      $e.append($("<p class='live'>").text("Live FAA status · " + code + ": " + text));
    });
    const $d = $("<details>").append($("<summary>").text("Assumptions and data"));
    $d.append(list("Assumptions", r.assumptions || []));
    $d.append($("<p>").text("Data period: " + r.data_period));
    $d.append($("<p class='call'>").text("Tool call: " + step.tool + "(" + JSON.stringify(step.arguments) + ")"));
    return $e.append($d);
  }

  function add(cls) {
    const $m = $("<div>").addClass("msg " + cls).appendTo($chat);
    return $m;
  }
  function scroll() { $chat.scrollTop($chat[0].scrollHeight); }

  // Hands-free loop: listen -> think -> speak -> listen. The mic is closed while the agent
  // thinks or speaks, so it never hears itself and never talks over you.
  function setStatus(text) { $("#hf-status").text(handsFree ? text : ""); }
  function listen() {
    if (!rec || !handsFree || speaking || $input.prop("disabled")) return;
    rec.continuous = false;  // hands-free relies on the browser's end-of-speech detection
    try { rec.start(); } catch (e) { /* already listening */ }
  }
  // The mic lives in the Send button's dropdown; while recording, Send itself becomes the stop button.
  function setMic(on) {
    $("#send").text(on ? "⏹ Stop and send" : "Send").toggleClass("rec", on);
  }
  function stopRecording() {
    ptt = false;
    pttSend = true;
    rec.stop();
  }
  function say(text) {
    speechSynthesis.cancel();
    const u = utterance = new SpeechSynthesisUtterance(text);
    $("#stop").prop("hidden", false);
    if (handsFree) {
      speaking = true;
      setStatus("Speaking…");
    }
    u.onend = u.onerror = () => {
      if (utterance !== u) return;  // superseded by a newer utterance
      $("#stop").prop("hidden", true);
      if (!speaking) return;
      speaking = false;
      listen();
    };
    speechSynthesis.speak(u);
  }

  // Stop reading aloud. In hands-free mode the loop carries on and listens again.
  function stopSpeaking() {
    speechSynthesis.cancel();  // fires onend/onerror of the current utterance, which cleans up
  }

  function send(text) {
    text = text.trim();
    if (!text || $input.prop("disabled")) return;
    if (ptt) { ptt = pttSend = false; rec.abort(); }  // sent by hand while recording
    add("user").text(text);
    stopSpeaking();
    $input.val("").prop("disabled", true);
    $("#send, #more").prop("disabled", true);
    setStatus("Thinking…");
    const $wait = add("agent wait").text("Thinking… a local model can take up to a minute.");
    scroll();
    $.ajax({ url: "/api/chat", method: "POST", contentType: "application/json",
             data: JSON.stringify({ session_id: sessionId, message: text }) })
      .done(res => {
        $wait.removeClass("wait").empty();
        $("<div class='answer'>").text(res.answer).appendTo($wait);
        res.trace.forEach(step => $wait.append(evidence(step)));
        if (($("#speak").prop("checked") || handsFree) && window.speechSynthesis) say(res.answer);
      })
      .fail(xhr => {
        const msg = (xhr.responseJSON && xhr.responseJSON.error) || "The server did not respond.";
        $wait.removeClass("wait").addClass("error").text(msg);
      })
      .always(() => {
        $input.prop("disabled", false).focus();
        $("#send, #more").prop("disabled", false);
        scroll();
        listen();
      });
  }

  $("#form").on("submit", e => {
    e.preventDefault();
    if (ptt) stopRecording(); else send($input.val());  // Send doubles as "stop and send" while recording
  });
  $("#stop").on("click", stopSpeaking);
  $chat.on("click", ".examples button", function () { send($(this).text()); });
  $("#reset").on("click", () => {
    $.ajax({ url: "/api/reset", method: "POST", contentType: "application/json",
             data: JSON.stringify({ session_id: sessionId }) });
    $chat.children().slice(1).remove();
  });

  // Server-side data store, read-only here: show what is loaded. While the server is still
  // downloading, the page is covered by the preparation message and polls until it is done.
  const POLL_MS = 2000;
  function fileRows($t, s) {
    $t.empty();
    s.files.forEach(f => $("<tr>").appendTo($t).append(
      $("<td>").text(f.ready ? "✓" : f.downloading ? "⏳" : "·"), $("<td>").text(f.description),
      $("<td>").text(f.ready ? f.rows.toLocaleString("en-US") + " rows"
                             : f.downloading ? "downloading…" : "waiting"),
      $("<td>").text(f.downloaded || "")));
  }
  function showData(s) {
    $("#data-dot").toggleClass("ok", s.ready);
    $("#data-label").text(s.ready ? "Data ready" : s.error ? "Data download failed" : "Preparing data…");
    fileRows($("#data-files"), s);
    fileRows($("#prep-files"), s);
    $("#form :input").prop("disabled", !s.ready);
    $("#prep").prop("hidden", s.ready);
    if (s.ready) return $input.focus();
    if (s.error) {
      $("#prep h2").text("Data download failed");
      $("#prep-text").addClass("error").text(s.error + ". Restart the server to try again.");
    } else {
      setTimeout(pollData, POLL_MS);
    }
  }
  function pollData() {
    $.getJSON("/api/data").done(showData).fail(() => setTimeout(pollData, POLL_MS));
  }
  pollData();

  // Voice (optional): browser speech recognition and synthesis, no server involved.
  // Push-to-talk and read-aloud are separate; hands-free is an opt-in checkbox, off by default.
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (window.speechSynthesis) $("#speak-label").prop("hidden", false);
  if (Recognition) {
    rec = new Recognition();
    rec.lang = "en-US";
    rec.interimResults = true;  // show the words as they are recognised
    rec.onstart = () => { $("#mic").addClass("on"); setStatus("Listening…"); };
    rec.onresult = e => {
      if (ptt) {  // continuous: results hold everything said since this session started
        const t = Array.from(e.results, r => r[0].transcript).join(" ");
        return $input.val((pttBase + " " + t).trim());
      }
      const r = e.results[e.results.length - 1];
      if (r.isFinal) send(r[0].transcript); else $input.val(r[0].transcript);
    };
    // In hands-free mode the browser ends the session on its own after you stop talking:
    // that is the end-of-speech detection, and listen() reopens it when it is our turn.
    // In push-to-talk only the mic button ends it; if the browser cuts in anyway, resume.
    rec.onend = () => {
      $("#mic").removeClass("on");
      if (ptt) {
        pttBase = $input.val();
        try { rec.start(); } catch (e) { /* already listening */ }
        return;
      }
      setMic(false);
      if (pttSend) { pttSend = false; return send($input.val()); }
      listen();
    };
    rec.onerror = e => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      ptt = pttSend = false;
      setMic(false);
      setHandsFree(false);
      add("agent error").text("Voice input stopped (" + e.error + "). Check the microphone permission.");
      scroll();
    };
    // Speak lives in the dropdown next to Send; Send stays the default action.
    const $menu = $("#menu");
    const closeMenu = () => { $menu.prop("hidden", true); $("#more").attr("aria-expanded", "false"); };
    $("#more").prop("hidden", false).on("click", e => {
      e.stopPropagation();
      const open = $menu.prop("hidden");
      $menu.prop("hidden", !open);
      $("#more").attr("aria-expanded", String(open));
    });
    $(document).on("click", closeMenu).on("keydown", e => { if (e.key === "Escape") closeMenu(); });
    $("#mic").on("click", () => {
      closeMenu();
      if (ptt) return stopRecording();
      ptt = true;
      pttBase = "";
      rec.continuous = true;
      setMic(true);
      try { rec.start(); } catch (e) { ptt = false; setMic(false); }
    });

    function setHandsFree(on) {
      handsFree = on;
      ptt = pttSend = false;
      setMic(false);
      $("#handsfree").prop("checked", on);
      $("#mic").prop("disabled", on);
      if (on) return listen();
      speaking = false;
      rec.abort();
      speechSynthesis.cancel();
      setStatus("");
    }
    if (window.speechSynthesis) {
      $("#handsfree-label").prop("hidden", false);
      $("#handsfree").on("change", function () { setHandsFree(this.checked); });
    }
  }
});
