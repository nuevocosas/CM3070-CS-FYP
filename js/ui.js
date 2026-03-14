var activeCard = null;

// load filter config so we can build the extra filter inputs
fetch("/config")
    .then(function(r) { return r.json(); })
    .then(function(cfg) {
        var wrap = document.getElementById("filterInputs");
        (cfg.filter_fields || []).forEach(function(f) {
            var lbl = document.createElement("label");
            lbl.style.cssText = "display:flex;align-items:center;gap:0.4rem";
            lbl.textContent = (f.label || f.field) + ":";

            var inp = document.createElement("input");
            inp.type = "text";
            inp.dataset.field = f.field;
            inp.placeholder = f.label || f.field;
            inp.style.cssText = "padding:0.3rem 0.5rem;border:1px solid #ccc;border-radius:4px;font-size:0.85rem;width:120px";
            inp.addEventListener("keydown", function(e) {
                if (e.key === "Enter") doSearch();
            });

            lbl.appendChild(inp);
            wrap.appendChild(lbl);
        });
    })
    .catch(function() {});

document.getElementById("queryInput").addEventListener("keydown", function(e) {
    if (e.key === "Enter") doSearch();
});

function doSearch() {
    var query = document.getElementById("queryInput").value.trim();
    if (!query) return;

    var limit = document.getElementById("limitSelect").value;
    var statusEl = document.getElementById("status");
    var resultsEl = document.getElementById("results");

    closePanel();
    statusEl.textContent = "Searching...";
    resultsEl.innerHTML = "";

    var qobj = { query: query, limit: parseInt(limit) };
    document.querySelectorAll("#filterInputs input[data-field]").forEach(function(inp) {
        var v = inp.value.trim();
        if (v) qobj[inp.dataset.field] = v;
    });

    var t0 = performance.now();
    fetch("/reconcile?query=" + encodeURIComponent(JSON.stringify(qobj)))
        .then(function(resp) {
            var ms = (performance.now() - t0).toFixed(0);
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            return resp.json().then(function(data) {
                var hits = data.result || [];
                statusEl.textContent = hits.length
                    ? hits.length + " result(s) in " + ms + "ms"
                    : "No matches (" + ms + "ms)";

                if (!hits.length) {
                    resultsEl.innerHTML = '<div class="empty">No matches found.</div>';
                    return;
                }

                hits.forEach(function(c) {
                    var card = document.createElement("div");
                    card.className = "result-card " + (c.match ? "match" : "no-match");
                    card.innerHTML =
                        '<div class="card-row">' +
                            '<span class="card-name">' + esc(c.name || "") + "</span>" +
                            '<span class="card-score">' + (c.score * 100).toFixed(1) + "%</span>" +
                        "</div>" +
                        '<div class="card-meta">' + esc(c.filter_value || "") +
                            (c.match ? " · Match" : " · Candidate") + "</div>";
                    card.addEventListener("click", function() { openDetail(c.id, card); });
                    resultsEl.appendChild(card);
                });
            });
        })
        .catch(function(err) {
            statusEl.textContent = "";
            resultsEl.innerHTML = '<div class="error">Error: ' + esc(err.message) + "</div>";
        });
}

function openDetail(id, card) {
    var panel = document.getElementById("detailPanel");

    if (activeCard === card && panel.classList.contains("open")) {
        closePanel();
        return;
    }

    if (activeCard) activeCard.classList.remove("active");
    activeCard = card;
    card.classList.add("active");
    panel.classList.add("open");
    document.getElementById("detailInner").innerHTML = "Loading...";

    fetch("/detail?id=" + encodeURIComponent(id))
        .then(function(resp) {
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            return resp.json();
        })
        .then(function(data) { renderDetail(data.result); })
        .catch(function(err) {
            document.getElementById("detailInner").innerHTML =
                '<span style="color:#c00">Failed: ' + esc(err.message) + "</span>";
        });
}

function closePanel() {
    document.getElementById("detailPanel").classList.remove("open");
    if (activeCard) {
        activeCard.classList.remove("active");
        activeCard = null;
    }
}

function renderDetail(r) {
    if (!r) return;

    function v(k) { return (r[k] || "").trim(); }

    var name = v("name_en") || v("unique_number");
    var desc = v("short_description_en");
    var idNo = v("id_no");

    var fields = [
        ["Country",     v("states_name_en")],
        ["Region",      v("region_en")],
        ["Category",    v("category")],
        ["Inscribed",   v("date_inscribed")],
        ["Area (ha)",   v("area_hectares")],
        ["Coordinates", v("latitude") && v("longitude") ? v("latitude") + ", " + v("longitude") : ""],
        ["Site ID",     idNo],
    ].filter(function(pair) { return pair[1]; });

    var html =
        '<button class="detail-close" onclick="closePanel()">x</button>' +
        "<h2>" + esc(name) + "</h2>";

    if (desc) html += '<div class="desc-box">' + desc + "</div>";

    html += '<dl class="fields">';
    fields.forEach(function(pair) {
        html += "<dt>" + esc(pair[0]) + "</dt><dd>" + esc(pair[1]) + "</dd>";
    });
    html += "</dl>";

    if (idNo) {
        html += '<p style="margin-top:0.75rem;font-size:0.8rem"><a href="https://whc.unesco.org/en/list/' +
            esc(idNo) + '" target="_blank">View on UNESCO website</a></p>';
    }

    document.getElementById("detailInner").innerHTML = html;
}

function esc(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
