// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// Roadmap Board
// A Kanban-style roadmap grid:
//   rows    = lanes (sprint prefix, or linked Project)
//   columns = weekly time windows, aligned across lanes, extended with empty
//             future windows for forward planning
//   cells   = the sprint in that lane/window, with status, story-point
//             acceptance %, and its work items (checkbox = accepted/Done)
//
// Work items can be dragged between sprints (and into empty future slots, which
// auto-create a Draft sprint). The checkbox is an acceptance indicator only.

const API_GET = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.get_roadmap_data";
const API_MOVE = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.move_work_item";
const SORTABLE_ASSET = "/assets/frappe_agile/js/vendor/sortable.min.js";
const MAX_ITEMS_VISIBLE = 6; // collapse longer item lists behind a "+N more"

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
			future_count: 8,
		};
		this._loading = false;
		this._sortables = [];
		this.can_write = frappe.model.can_write("Work Item");

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
			<div class="rm-filter-group">
				<span class="rm-filter-label">${__("Plan ahead")}</span>
				<select id="rm-future" class="form-control input-xs">
					<option value="4">${__("4 sprints")}</option>
					<option value="8" selected>${__("8 sprints")}</option>
					<option value="12">${__("12 sprints")}</option>
					<option value="20">${__("20 sprints")}</option>
				</select>
			</div>
			<div class="rm-filter-group rm-filter-grow">
				<span class="rm-filter-label">${__("Search work item / sprint")}</span>
				<input type="text" id="rm-search" class="form-control input-xs"
					placeholder="${__("Type to highlight matches…")}" />
			</div>
			<div class="rm-filters-actions">
				<button class="btn btn-default btn-xs" id="rm-jump-current" title="${__("Scroll to current sprint")}">
					<i class="fa fa-crosshairs"></i> ${__("Today")}
				</button>
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
		this.$filters.find("#rm-future").on("change", (e) => {
			this.filters.future_count = cint(e.target.value);
			this.refresh();
		});
		this.$filters.find("#rm-search").on("input", frappe.utils.debounce((e) => {
			this.filters.search = e.target.value;
			this._render_grid(); // search highlights client-side, no server round-trip
		}, 200));
		this.$filters.find("#rm-refresh").on("click", () => this.refresh());
		this.$filters.find("#rm-jump-current").on("click", () => this._scroll_to_current());
	}

	_render_legend() {
		const drag_hint = this.can_write
			? `<span class="rm-legend-item"><i class="fa fa-arrows"></i> ${__("Drag work items between sprints")}</span>`
			: `<span class="rm-legend-item rm-readonly"><i class="fa fa-lock"></i> ${__("Read-only — no Work Item write access")}</span>`;
		this.$legend.html(`
			<span class="rm-legend-item"><span class="rm-dot rm-status-draft"></span>${__("Draft")}</span>
			<span class="rm-legend-item"><span class="rm-dot rm-status-active"></span>${__("Active")}</span>
			<span class="rm-legend-item"><span class="rm-dot rm-status-completed"></span>${__("Completed")}</span>
			<span class="rm-legend-sep"></span>
			<span class="rm-legend-item"><i class="fa fa-check-square-o"></i> ${__("Accepted (Done)")}</span>
			<span class="rm-legend-item rm-legend-pct">${__("% = story-point acceptance")}</span>
			<span class="rm-legend-sep"></span>
			${drag_hint}
		`);
	}

	// ----------------------------------------------------------
	// Data load
	// ----------------------------------------------------------
	refresh() {
		if (this._loading) return;
		this._loading = true;
		this._destroy_sortables();
		this.$grid.html(this._skeleton_html());

		frappe.call({
			method: API_GET,
			args: {
				group_by: this.filters.group_by,
				lane: this.filters.lane || undefined,
				sprint_status: this.filters.sprint_status || undefined,
				search: this.filters.search || undefined,
				future_count: this.filters.future_count,
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
		const template_cols = `var(--rm-lane-w) repeat(${cols.length}, var(--rm-col-w))`;

		let html = `<div class="rm-grid" style="grid-template-columns:${template_cols}">`;

		// --- Header row ---
		html += `<div class="rm-corner">${__("Projects / Sprints")}</div>`;
		cols.forEach((c) => {
			const dates = this._fmt_range(c.start_date, c.end_date);
			const cls = `${c.is_current ? "rm-current" : ""} ${c.is_future ? "rm-future" : ""}`;
			const tag = c.is_current
				? `<div class="rm-colhead-tag rm-tag-current">${__("CURRENT")}</div>`
				: c.is_future
					? `<div class="rm-colhead-tag rm-tag-future">${__("UPCOMING")}</div>`
					: "";
			html += `
				<div class="rm-colhead ${cls}" data-col="${frappe.utils.escape_html(c.key)}">
					<div class="rm-colhead-title">${frappe.utils.escape_html(c.label)}</div>
					<div class="rm-colhead-dates">${dates}</div>
					${tag}
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
				const cell = data.cells[`${row.key}::${c.key}`];
				html += cell
					? this._cell_html(cell, row, c, term)
					: this._empty_cell_html(row, c);
			});
		});

		html += `</div>`;
		this.$grid.html(html);
		this._bind_cell_events();
		this._init_drag();
		this._scroll_to_current();
	}

	_cell_attrs(cell, row, col) {
		const locked = cell && cell.status === "Completed" ? "1" : "0";
		return `
			data-sprint="${cell ? frappe.utils.escape_html(cell.sprint) : ""}"
			data-lane="${frappe.utils.escape_html(row.key)}"
			data-window-start="${col.start_date || ""}"
			data-window-end="${col.end_date || ""}"
			data-locked="${locked}"`;
	}

	_cell_html(cell, row, col, term) {
		const status_class = this._status_class(cell.status);
		const pct = cell.acceptance_pct;
		const pct_class = pct >= 100 ? "rm-pct-full" : pct >= 50 ? "rm-pct-mid" : "rm-pct-low";
		const matched = term && cell.search_matched ? "rm-matched" : "";
		const locked = cell.status === "Completed";

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

		return `
		<div class="rm-cell ${matched} ${locked ? "rm-locked" : ""}" ${this._cell_attrs(cell, row, col)}>
			<div class="rm-cell-head">
				<a class="rm-sprint-name" href="/app/sprint/${encodeURIComponent(cell.sprint)}"
					title="${__("Open sprint")}">${frappe.utils.escape_html(cell.sprint)}</a>
				<span class="rm-badge ${status_class}">${frappe.utils.escape_html(cell.status || "—")}</span>
			</div>
			<div class="rm-items" data-droppable="1">${items_html}</div>
			<div class="rm-cell-foot">
				<div class="rm-points"><strong>${cell.total_points}</strong> ${__("SP")}</div>
				<div class="rm-pct ${pct_class}">${pct}%</div>
			</div>
			<div class="rm-progress">
				<div class="rm-progress-bar ${pct_class}" style="width:${Math.min(pct, 100)}%"></div>
			</div>
		</div>`;
	}

	_empty_cell_html(row, col) {
		const can_plan = this.can_write && this.filters.group_by === "sprint_prefix";
		const hint = can_plan
			? `<div class="rm-empty-hint">${col.is_future ? __("Drop to plan here") : __("Drop here")}</div>`
			: "";
		return `
		<div class="rm-cell rm-cell-empty ${col.is_future ? "rm-cell-future" : ""}" ${this._cell_attrs(null, row, col)}>
			<div class="rm-items" data-droppable="${can_plan ? "1" : "0"}"></div>
			${hint}
		</div>`;
	}

	_item_html(wi, term) {
		const checked = wi.accepted ? "checked" : "";
		const acc_class = wi.accepted ? "rm-item-accepted" : "";
		const type_class = `rm-type-${(wi.type || "").toLowerCase().replace(/\s+/g, "-")}`;
		const highlight = term && (wi.title || "").toLowerCase().includes(term) ? "rm-item-hit" : "";
		const pts = wi.story_points ? `<span class="rm-item-pts">${wi.story_points}</span>` : "";
		const handle = this.can_write
			? `<span class="rm-item-drag" title="${__("Drag to another sprint")}">⠿</span>`
			: "";

		return `
		<div class="rm-item ${acc_class} ${highlight}" data-name="${frappe.utils.escape_html(wi.name)}"
			title="${frappe.utils.escape_html((wi.type || "") + " · " + (wi.status || ""))}">
			${handle}
			<input type="checkbox" class="rm-check" ${checked} disabled />
			<span class="rm-item-type ${type_class}"></span>
			<a class="rm-item-title" href="/app/work-item/${encodeURIComponent(wi.name)}" target="_blank"
				title="${frappe.utils.escape_html(wi.title || "")}">${frappe.utils.escape_html(wi.title || wi.name)}</a>
			${pts}
		</div>`;
	}

	_bind_cell_events() {
		this.$grid.find(".rm-more").on("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const sprint = $(e.currentTarget).data("sprint");
			const cell = this._find_cell_by_sprint(sprint);
			if (!cell) return;
			const term = (this.filters.search || "").trim().toLowerCase();
			const $items = $(e.currentTarget).closest(".rm-items");
			$items.html(cell.work_items.map((wi) => this._item_html(wi, term)).join(""));
			this._init_drag(); // re-init sortable to include newly shown items
		});
	}

	// ----------------------------------------------------------
	// Drag & drop
	// ----------------------------------------------------------
	_init_drag() {
		if (!this.can_write) return;
		frappe.require(SORTABLE_ASSET, () => {
			this._destroy_sortables();
			this.$grid.find('.rm-items[data-droppable]').each((i, list) => {
				const droppable = list.getAttribute("data-droppable") === "1";
				const s = new Sortable(list, {
					group: {
						name: "roadmap",
						pull: true,
						// allow drop only into non-completed, droppable cells
						put: (to) => {
							const cell = to.el.closest(".rm-cell");
							return cell
								&& cell.dataset.locked !== "1"
								&& to.el.getAttribute("data-droppable") === "1";
						},
					},
					sort: false,
					draggable: ".rm-item",
					handle: ".rm-item-drag",
					animation: 150,
					ghostClass: "rm-drag-ghost",
					chosenClass: "rm-drag-chosen",
					filter: ".rm-item-title, .rm-check",
					preventOnFilter: false,
					onEnd: (evt) => this._on_item_moved(evt),
				});
				// A non-droppable list can still be a drag source.
				if (!droppable) s.option("group", { name: "roadmap", pull: true, put: false });
				this._sortables.push(s);
			});
		});
	}

	_destroy_sortables() {
		(this._sortables || []).forEach((s) => {
			try { s.destroy(); } catch (e) { /* ignore */ }
		});
		this._sortables = [];
	}

	_on_item_moved(evt) {
		const fromCell = evt.from.closest(".rm-cell");
		const toCell = evt.to.closest(".rm-cell");
		if (!toCell || fromCell === toCell) return; // dropped back in place

		const work_item = evt.item.getAttribute("data-name");
		const target_sprint = toCell.dataset.sprint || "";
		const lane = toCell.dataset.lane || "";
		const window_start = toCell.dataset.windowStart || "";
		const window_end = toCell.dataset.windowEnd || "";

		frappe.dom.freeze(__("Moving work item…"));
		frappe.call({
			method: API_MOVE,
			args: {
				work_item,
				target_sprint: target_sprint || undefined,
				lane,
				group_by: this.filters.group_by,
				window_start,
				window_end,
			},
			callback: (r) => {
				frappe.dom.unfreeze();
				const m = r && r.message;
				if (m && !m.unchanged) {
					const dest = m.target_sprint + (m.created ? __(" (new sprint created)") : "");
					frappe.show_alert({
						message: __("Moved {0} → {1}", [work_item, dest]),
						indicator: "green",
					});
				}
				this.refresh();
			},
			error: (err) => {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __("Move failed: {0}", [(err && err.message) || __("see error log")]),
					indicator: "red",
				});
				this.refresh(); // reload to restore correct positions
			},
		});
	}

	_find_cell_by_sprint(sprint) {
		return Object.values(this.data.cells).find((c) => c.sprint === sprint);
	}

	// ----------------------------------------------------------
	// Helpers
	// ----------------------------------------------------------
	_scroll_to_current() {
		const $cur = this.$grid.find(".rm-colhead.rm-current");
		if (!$cur.length) return;
		const scroller = this.$grid[0];
		const left = $cur[0].offsetLeft - scroller.clientWidth / 2 + $cur[0].offsetWidth / 2;
		scroller.scrollTo({ left: Math.max(left, 0), behavior: "smooth" });
	}

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
