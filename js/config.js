var SWATCH = ["#e53935", "#8e24aa", "#1e88e5", "#00897b", "#f4511e", "#6d4c41"];

var allCols = [];
var filterList = [];

fetch("/config")
    .then(function (r) {
        return r.json();
    })
    .then(function (cfg) {
        allCols = cfg.all_fields || [];
        filterList = (cfg.filter_fields || []).map(function (f) {
            return Object.assign({}, f);
        });

        var info = [
            ["Dataset", cfg.dataset],
            ["ID field", cfg.id_field],
            ["Name field", cfg.name_field],
            ["Algorithm", cfg.algorithm],
            ["Columns", allCols.length],
        ];
        document.getElementById("datasetInfo").innerHTML = info
            .map(function (pair) {
                return "<dt>" + esc(pair[0]) + "</dt><dd>" + esc(String(pair[1] || "")) + "</dd>";
            })
            .join("");

        redraw();
    });

function redraw() {
    var list = document.getElementById("filterList");

    if (!filterList.length) {
        list.innerHTML = '<div class="empty-filters">No filters yet. Click "+ Add Filter" to add one.</div>';
        updateBar();
        return;
    }

    list.innerHTML = "";
    filterList.forEach(function (row, i) {
        var div = document.createElement("div");
        div.className = "filter-row";
        div.style.borderLeftColor = SWATCH[i % SWATCH.length];

        var opts = allCols
            .map(function (col) {
                return (
                    '<option value="' +
                    esc(col) +
                    '"' +
                    (col === row.field ? " selected" : "") +
                    ">" +
                    esc(col) +
                    "</option>"
                );
            })
            .join("");

        div.innerHTML =
            '<div class="field-group">' +
            "<label>Column</label>" +
            '<select onchange="edit(' +
            i +
            ",'field',this.value)\">" +
            opts +
            "</select>" +
            "</div>" +
            '<div class="field-group">' +
            "<label>Label</label>" +
            '<input type="text" value="' +
            esc(row.label || row.field) +
            '" oninput="edit(' +
            i +
            ",'label',this.value)\" />" +
            "</div>" +
            '<div class="field-group">' +
            "<label>Weight</label>" +
            '<div class="weight-wrap">' +
            '<input type="number" value="' +
            row.weight +
            '" min="0.01" max="0.99" step="0.05"' +
            ' oninput="edit(' +
            i +
            ",'weight',parseFloat(this.value)||0)\" />" +
            '<span class="weight-pct">wt</span>' +
            "</div>" +
            "</div>" +
            '<button class="btn-remove" onclick="removeRow(' +
            i +
            ')">x</button>';

        list.appendChild(div);
    });

    updateBar();
}

function edit(i, key, val) {
    filterList[i][key] = val;
    if (key === "field" && !filterList[i].label) filterList[i].label = val;
    updateBar();
}

function addRow() {
    var used = filterList.map(function (r) {
        return r.field;
    });
    var next =
        allCols.find(function (c) {
            return used.indexOf(c) === -1;
        }) ||
        allCols[0] ||
        "";
    filterList.push({ field: next, label: next, weight: 0.2 });
    redraw();
}

function removeRow(i) {
    filterList.splice(i, 1);
    redraw();
}

function updateBar() {
    var total = filterList.reduce(function (s, r) {
        return s + (parseFloat(r.weight) || 0);
    }, 0);
    var nameW = Math.max(0, 1 - total);
    var ok = total < 1;

    document.getElementById("weightError").style.display = ok ? "none" : "block";
    document.getElementById("saveBtn").disabled = !ok;

    // rebuild the bar segments
    var bar = document.getElementById("weightBar");
    bar.innerHTML = '<div style="flex:' + nameW + ";background:#3949ab;min-width:" + (nameW > 0 ? 2 : 0) + 'px"></div>';
    filterList.forEach(function (r, i) {
        var seg = document.createElement("div");
        var w = parseFloat(r.weight) || 0;
        seg.style.flex = String(w);
        seg.style.background = SWATCH[i % SWATCH.length];
        seg.style.minWidth = w > 0 ? "2px" : "0";
        bar.appendChild(seg);
    });

    // rebuild the legend
    var legend = document.getElementById("weightLegend");
    legend.innerHTML =
        '<span><span class="legend-dot" style="background:#3949ab"></span>Name (' +
        (nameW * 100).toFixed(0) +
        "%)</span>";
    filterList.forEach(function (r, i) {
        var w = (parseFloat(r.weight) || 0) * 100;
        legend.innerHTML +=
            '<span><span class="legend-dot" style="background:' +
            SWATCH[i % SWATCH.length] +
            '"></span>' +
            esc(r.label || r.field) +
            " (" +
            w.toFixed(0) +
            "%)</span>";
    });
}

function saveConfig() {
    var statusEl = document.getElementById("saveStatus");
    statusEl.textContent = "Saving...";
    statusEl.className = "save-status";

    // read back from DOM in case user edited manually
    var rows = [];
    document.querySelectorAll(".filter-row").forEach(function (div) {
        var field = div.querySelector("select").value;
        var inputs = div.querySelectorAll("input");
        rows.push({
            field: field,
            label: inputs[0].value.trim() || field,
            weight: parseFloat(inputs[1].value) || 0,
        });
    });

    fetch("/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filter_fields: rows }),
    })
        .then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok || data.code === "error") throw new Error(data.message || "HTTP " + resp.status);
                filterList = data.filter_fields.map(function (f) {
                    return Object.assign({}, f);
                });
                redraw();
                statusEl.textContent = "Saved. Name weight is now " + (data.name_weight * 100).toFixed(0) + "%.";
                statusEl.className = "save-status ok";
                setTimeout(function () {
                    statusEl.textContent = "";
                }, 4000);
            });
        })
        .catch(function (err) {
            statusEl.textContent = "Error: " + err.message;
            statusEl.className = "save-status error";
        });
}

function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
