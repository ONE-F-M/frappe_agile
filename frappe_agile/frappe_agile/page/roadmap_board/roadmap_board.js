// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// Roadmap Board
// A Kanban-style roadmap grid:
//   rows    = lanes (sprint prefix, or linked Project)
//   columns = weekly time windows, aligned across lanes
//   cells   = the sprint in that lane/window, with status, story-point
//             acceptance %, and its work items (checkbox = accepted/Done)
//
// Read-only view: it surfaces and links into the Sprint / Work Item docs but
// does not write. The checkbox is an acceptance indicator, not an editor.

const API = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.get_roadmap_data";
const MAX_ITEMS_VISIBLE = 5; // collapse longer item lists behind a "+N more"

frappe.pages["roadmap-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Roadmap"),
		single_column: true,
	});

	wrapper.roadmap_board = new RoadmapBoard(page, wrapper);
};

frappe.pages["roadmap-board"].on_page_show = function (wrapper) {
	if (wrapper.roadmap_board) {
		wrapper.roadmap_board.refresh();
	}
};

class RoadmapBoard {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;

		this.filters = {
			group_by: "sprint_prefix",
			lane: "",
			sprint_status: "",
			search: "",
		};
		this._loading = false;

		this._build_ui();
		this.refresh();
	}

	// ----------------------------------------------------------
	// UI skeleton + filters
	// ----------------------------------------------------------
	_build_ui() {
		const $body = $(this.page.body);
		$body.empty();
		$body.append(`
			<div class="rm-wrapper">
				<div class="rm-filters" id="rm-filters"></div>
				<div class="rm-legend" id="rm-legend"></div>
				<div class="rm-grid-scroll" id="rm-grid-scroll">
					${this._skeleton_html()}
				</div>
			</div>
		`);

		this.$filters = $body.find("#rm-filters");
		this.$legend = $body.find("#rm-legend");
		this.$grid = $body.find("#rm-grid-scroll");

		this._render_filters();
		this._render_legend();
	}

	_render_filters() {
		this.$filters.html(`
			<div class="rm-filter-group">
				<span class="rm-filter-label">${__("Group rows by")}</span>
				<select id="rm-group-by" class="form-control input-xs">
					<option value="sprint_prefix">${__("Sprint Prefix / Track")}</option>
					<option value="project">${__("Project")}</option>
				</select>
			</div>
			<div class="rm-filter-group">
				<span class="rm-filter-label">${__("Sprint Status")}</span>
				<select id="rm-status" class="form-control input-xs">
					<option value="">${__("All Statuses")}</option>
					<option value="Draft">${__("Draft")}</option>
					<option value="Active">${__("Active")}</option>
					<option value="Completed">${__("Completed")}</option>
				</select>
			</div>
			<div class="rm-filter-group rm-filter-grow">
				<span class="rm-filter-label">${__("Search work item / sprint")}</span>
				<input type="text" id="rm-search" class="form-control input-xs"
					placeholder="${__("Type to highlight matches…")}" />
			</div>
			<div class="rm-filters-actions">
				<button class="btn btn-primary btn-xs" id="rm-refresh">
					<i class="fa fa-refresh"></i> ${__("Refresh")}
				</button>
			</div>
		`);

		this.$filters.find("#rm-group-by").on("change", (e) => {
			this.filters.group_by = e.target.value;
			this.filters.lane = "";
			this.refresh();
		});
		this.$filters.find("#rm-status").on("change", (e) => {
			this.filters.sprint_status = e.target.value;
			this.refresh();
		});
		this.$filters.find("#rm-search").on("input", frappe.utils.debounce((e) => {
			this.filters.search = e.target.value;
			this._render_grid(); // search highlights client-side, no server round-trip
		}, 200));
		this.$filters.find("#rm-refresh").on("click", () => this.refresh());
	}

	_render_legend() {
		this.$legend.html(`
			<span class="rm-legend-item"><span class="rm-dot rm-status-draft"></span>${__("Draft")}</span>
			<span class="rm-legend-item"><span class="rm-dot rm-status-active"></span>${__("Active")}</span>
			<span class="rm-legend-item"><span class="rm-dot rm-status-completed"></span>${__("Completed")}</span>
			<span class="rm-legend-sep"></span>
			<span class="rm-legend-item"><i class="fa fa-check-square-o"></i> ${__("Accepted work item (Done)")}</span>
			<span class="rm-legend-item rm-legend-pct">${__("% = story-point acceptance")}</span>
		`);
	}

	// ----------------------------------------------------------
	// Data load
	// ----------------------------------------------------------
	refresh() {
		if (this._loading) return;
		this._loading = true;
		this.$grid.html(this._skeleton_html());

		frappe.call({
			method: API,
			args: {
				group_by: this.filters.group_by,
				lane: this.filters.lane || undefined,
				sprint_status: this.filters.sprint_status || undefined,
				search: this.filters.search || undefined,
			},
			callback: (r) => {
				this._loading = false;
				this.data = (r && r.message) || { columns: [], rows: [], cells: {} };
				this._render_grid();
			},
			error: (err) => {
				this._loading = false;
				this.$grid.html(`
					<div class="rm-empty">
						<div class="rm-empty-icon">⚠️</div>
						<p>${__("Failed to load roadmap.")} ${frappe.utils.escape_html((err && err.message) || "")}</p>
					</div>
				`);
			},
		});
	}

	// ----------------------------------------------------------
	// Grid render
	// ----------------------------------------------------------
	_render_grid() {
		const data = this.data;
		if (!data || !data.rows.length || !data.columns.length) {
			this.$grid.html(`
				<div class="rm-empty">
					<div class="rm-empty-icon">🗺️</div>
					<p>${__("No sprints found for the current filters.")}</p>
				</div>
			`);
			return;
		}

		const term = (this.filters.search || "").trim().toLowerCase();
		const cols = data.columns;

		// CSS grid: first column = lane header (sticky), then one per window.
		const template_cols = `var(--rm-lane-w) repeat(${cols.length}, var(--rm-col-w))`;

		let html = `<div class="rm-grid" style="grid-template-columns:${template_cols}">`;

		// --- Header row ---
		html += `<div class="rm-corner">${__("Projects / Sprints")}</div>`;
		cols.forEach((c) => {
			const dates = this._fmt_range(c.start_date, c.end_date);
			html += `
				<div class="rm-colhead ${c.is_current ? "rm-current" : ""}">
					<div class="rm-colhead-title">${frappe.utils.escape_html(c.label)}</div>
					<div class="rm-colhead-dates">${dates}</div>
					${c.is_current ? `<div class="rm-colhead-current">${__("CURRENT")}</div>` : ""}
				</div>`;
		});

		// --- Body rows ---
		data.rows.forEach((row) => {
			const proj = row.projects && row.projects.length
				? frappe.utils.escape_html(row.projects.join(", "))
				: __("No linked project");
			html += `
				<div class="rm-lanehead">
					<div class="rm-lane-bar"></div>
					<div class="rm-lane-text">
						<div class="rm-lane-title">${frappe.utils.escape_html(row.label)}</div>
						<div class="rm-lane-sub">${proj}</div>
					</div>
				</div>`;

			cols.forEach((c) => {
				const cell_key = `${row.key}::${c.key}`;
				const cell = data.cells[cell_key];
				html += cell
					? this._cell_html(cell, term)
					: `<div class="rm-cell rm-cell-empty"></div>`;
			});
		});

		html += `</div>`;
		this.$grid.html(html);
		this._bind_cell_events();
	}

	_cell_html(cell, term) {
		const status_class = this._status_class(cell.status);
		const pct = cell.acceptance_pct;
		const pct_class = pct >= 100 ? "rm-pct-full" : pct >= 50 ? "rm-pct-mid" : "rm-pct-low";
		const matched = term && cell.search_matched ? "rm-matched" : "";

		const items = cell.work_items || [];
		const visible = items.slice(0, MAX_ITEMS_VISIBLE);
		const hidden = items.length - visible.length;

		let items_html = visible.map((wi) => this._item_html(wi, term)).join("");
		if (hidden > 0) {
			items_html += `
				<button class="rm-more" data-sprint="${frappe.utils.escape_html(cell.sprint)}">
					+${hidden} ${__("more")}
				</button>`;
		}
		if (!items.length) {
			items_html = `<div class="rm-no-items">${__("No work items")}</div>`;
		}

		return `
		<div class="rm-cell ${matched}" data-sprint="${frappe.utils.escape_html(cell.sprint)}">
			<div class="rm-cell-head">
				<a class="rm-sprint-name" href="/app/sprint/${encodeURIComponent(cell.sprint)}"
					title="${__("Open sprint")}">${frappe.utils.escape_html(cell.sprint)}</a>
				<span class="rm-badge ${status_class}">${frappe.utils.escape_html(cell.status || "—")}</span>
			</div>
			<div class="rm-items">${items_html}</div>
			<div class="rm-cell-foot">
				<div class="rm-points">
					<strong>${cell.total_points}</strong> ${__("SP")}
				</div>
				<div class="rm-pct ${pct_class}">${pct}%</div>
			</div>
			<div class="rm-progress">
				<div class="rm-progress-bar ${pct_class}" style="width:${Math.min(pct, 100)}%"></div>
			</div>
		</div>`;
	}

	_item_html(wi, term) {
		const checked = wi.accepted ? "checked" : "";
		const acc_class = wi.accepted ? "rm-item-accepted" : "";
		const type_class = `rm-type-${(wi.type || "").toLowerCase().replace(/\s+/g, "-")}`;
		const highlight = term && (wi.title || "").toLowerCase().includes(term) ? "rm-item-hit" : "";
		const pts = wi.story_points ? `<span class="rm-item-pts">${wi.story_points}</span>` : "";

		return `
		<label class="rm-item ${acc_class} ${highlight}" title="${frappe.utils.escape_html(wi.status || "")}">
			<input type="checkbox" class="rm-check" ${checked} disabled />
			<span class="rm-item-type ${type_class}" title="${frappe.utils.escape_html(wi.type || "")}"></span>
			<a class="rm-item-title" href="/app/work-item/${encodeURIComponent(wi.name)}" target="_blank"
				title="${frappe.utils.escape_html(wi.title || "")}">${frappe.utils.escape_html(wi.title || wi.name)}</a>
			${pts}
		</label>`;
	}

	_bind_cell_events() {
		// "+N more" expands a cell to show all items for that sprint.
		this.$grid.find(".rm-more").on("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const sprint = $(e.currentTarget).data("sprint");
			const cell = this._find_cell_by_sprint(sprint);
			if (!cell) return;
			const term = (this.filters.search || "").trim().toLowerCase();
			const $items = $(e.currentTarget).closest(".rm-items");
			$items.html(cell.work_items.map((wi) => this._item_html(wi, term)).join(""));
		});
	}

	_find_cell_by_sprint(sprint) {
		return Object.values(this.data.cells).find((c) => c.sprint === sprint);
	}

	// ----------------------------------------------------------
	// Helpers
	// ----------------------------------------------------------
	_fmt_range(start, end) {
		if (!start) return "";
		const s = frappe.datetime.str_to_obj(start);
		const fmt = (d) => `${d.toLocaleString("en", { month: "short" })} ${d.getDate()}`;
		if (!end) return fmt(s);
		const e = frappe.datetime.str_to_obj(end);
		return `${fmt(s)} – ${fmt(e)}`;
	}

	_status_class(status) {
		return {
			Draft: "rm-status-draft",
			Active: "rm-status-active",
			Completed: "rm-status-completed",
		}[status] || "rm-status-draft";
	}

	_skeleton_html() {
		return `<div class="rm-skeleton">${Array(8).fill('<div class="rm-skel-card"></div>').join("")}</div>`;
	}
}
