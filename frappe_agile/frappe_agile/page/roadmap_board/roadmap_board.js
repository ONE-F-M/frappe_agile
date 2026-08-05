// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// Roadmap Board
// A Kanban-style roadmap grid:
//   rows    = one lane per active SCRUM Project (always — there is no other
//             grouping); projects with no sprints yet still get a lane
//   columns = weekly time windows, aligned across lanes, extended with empty
//             future windows for forward planning
//   cells   = the sprint in that project/window, with status, story-point
//             acceptance %, and its work items (checkbox = accepted/Done)
//
// Work items can be dragged between sprints (and into empty future slots, which
// auto-create a Draft sprint named from the project's Sprint Prefix). The
// checkbox is an acceptance indicator only.
//
// A Backlog panel on the left lists Work Items not yet on any sprint (newest
// first); items can be dragged from it straight onto a sprint cell.

const API_GET = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.get_roadmap_data";
const API_MOVE = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.move_work_item";
const API_CREATE_MISSING = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.create_missing_sprints";
const API_BACKLOG = "frappe_agile.frappe_agile.page.roadmap_board.roadmap_board.get_unassigned_work_items";
const SORTABLE_ASSET = "/assets/frappe_agile/js/vendor/sortable.min.js";
const MAX_ITEMS_VISIBLE = 6; // collapse longer item lists behind a "+N more"
// Project.status options — the values the Project Status multi-select offers.
const PROJECT_STATUSES = ["Open", "Completed", "Cancelled"];

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
			// Multi-select of Project statuses; empty = every status (the board is
			// already restricted to active SCRUM projects server-side).
			project_status: [],
			lane: "",
			sprint_status: "",
			search: "",
			future_count: 8,
		};
		this._loading = false;
		this._sortables = [];
		// Backlog (left panel) state + its own Sortable instance, kept separate
		// from the grid sortables so a grid-only re-render doesn't drop it.
		this.backlog = [];
		this._backlog_sortable = null;
		// The backlog is a collapsible left drawer; remember the user's choice so
		// the roadmap keeps the full width when they leave it closed.
		this._backlog_open = this._read_backlog_pref();
		// Selection mode: clicking "Create Missing Sprint(s)" reveals per-project
		// checkboxes; sprints for the picked projects are created on Confirm.
		this._selecting = false;
		this.selected_lanes = new Set();
		// Epics render collapsed by default; remember which ones the user expanded
		// (keyed by `sprint::epic`) so an in-place refresh keeps them open.
		this._expanded_epics = new Set();
		this.can_write = frappe.model.can_write("Work Item");
		this.can_create_wi = frappe.model.can_create("Work Item");
		this.can_create_sprint = frappe.model.can_create("Sprint");

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
				<div class="rm-main" id="rm-main">
					<aside class="rm-backlog" id="rm-backlog">
						<div class="rm-backlog-head">
							<div class="rm-backlog-title">
								<i class="fa fa-inbox"></i> ${__("Backlog")}
								<span class="rm-backlog-count" id="rm-backlog-count">0</span>
								<button class="rm-backlog-collapse" id="rm-backlog-collapse"
									title="${__("Hide backlog")}"><i class="fa fa-angle-double-left"></i></button>
							</div>
							<div class="rm-backlog-sub">${__("Unassigned — drag onto a sprint")}</div>
						</div>
						<div class="rm-backlog-list" id="rm-backlog-list" data-droppable="0">
							${this._backlog_skeleton_html()}
						</div>
					</aside>
					<div class="rm-grid-scroll" id="rm-grid-scroll">
						${this._skeleton_html()}
					</div>
				</div>
			</div>
		`);

		this.$filters = $body.find("#rm-filters");
		this.$legend = $body.find("#rm-legend");
		this.$grid = $body.find("#rm-grid-scroll");
		this.$main = $body.find("#rm-main");
		this.$backlog = $body.find("#rm-backlog");
		this.$backlog_list = $body.find("#rm-backlog-list");
		this.$backlog_count = $body.find("#rm-backlog-count");

		$body.find("#rm-backlog-collapse").on("click", () => this._toggle_backlog());

		this._render_filters();
		this._render_legend();

		// Apply the remembered open/closed state (also syncs the toggle button).
		this._apply_backlog_state();
	}

	_render_filters() {
		this.$filters.html(`
			<div class="rm-filter-group">
				<span class="rm-filter-label">${__("Project Status")}</span>
				<div id="rm-project-status" class="rm-multiselect"></div>
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
				<button class="btn btn-default btn-xs" id="rm-backlog-toggle" title="${__("Show / hide the backlog")}">
					<i class="fa fa-columns"></i> ${__("Backlog")}
					<span class="rm-backlog-toggle-count" id="rm-backlog-toggle-count">0</span>
				</button>
				<span class="rm-select-hint">${__("Tick the projects to create sprints for, then Confirm")}</span>
				<button class="btn btn-default btn-xs" id="rm-create-missing" title="${__("Create Draft sprints for upcoming windows that have none")}">
					<i class="fa fa-plus"></i> ${__("Create Missing Sprint(s)")}
				</button>
				<button class="btn btn-primary btn-xs" id="rm-confirm-create" title="${__("Create sprints for the ticked projects")}">
					<i class="fa fa-check"></i> <span class="rm-confirm-label">${__("Confirm")}</span>
				</button>
				<button class="btn btn-default btn-xs" id="rm-cancel-create">
					${__("Cancel")}
				</button>
				<button class="btn btn-default btn-xs" id="rm-jump-current" title="${__("Scroll to current sprint")}">
					<i class="fa fa-crosshairs"></i> ${__("Today")}
				</button>
				<button class="btn btn-primary btn-xs" id="rm-refresh">
					<i class="fa fa-refresh"></i> ${__("Refresh")}
				</button>
			</div>
		`);

		this._make_project_status_filter();
		this.$filters.find("#rm-status").on("change", (e) => {
			this.filters.sprint_status = e.target.value;
			this.refresh({ scrollToCurrent: true });
		});
		this.$filters.find("#rm-future").on("change", (e) => {
			this.filters.future_count = cint(e.target.value);
			this.refresh({ scrollToCurrent: true });
		});
		this.$filters.find("#rm-search").on("input", frappe.utils.debounce((e) => {
			this.filters.search = e.target.value;
			this._render_grid(); // search highlights client-side, no server round-trip
			this._render_backlog();
		}, 200));
		this.$filters.find("#rm-refresh").on("click", () => this.refresh({ preserveScroll: true }));
		this.$filters.find("#rm-jump-current").on("click", () => this._scroll_to_current());
		this.$filters.find("#rm-create-missing").on("click", () => this._enter_selection_mode());
		this.$filters.find("#rm-confirm-create").on("click", () => this._on_create_missing());
		this.$filters.find("#rm-cancel-create").on("click", () => this._exit_selection_mode());
		this.$filters.find("#rm-backlog-toggle").on("click", () => this._toggle_backlog());
		this.$backlog_toggle = this.$filters.find("#rm-backlog-toggle");
		this.$backlog_toggle_count = this.$filters.find("#rm-backlog-toggle-count");

		this.$create_missing = this.$filters.find("#rm-create-missing");
		this.$confirm_create = this.$filters.find("#rm-confirm-create");
		this.$cancel_create = this.$filters.find("#rm-cancel-create");
		this.$select_hint = this.$filters.find(".rm-select-hint");
		// The create controls are all hidden until data says a project is missing a
		// sprint; confirm/cancel/hint appear only while in selection mode.
		this._update_create_controls();
	}

	// Project Status is a multi-select: the board is always restricted to active
	// SCRUM projects, and this narrows that set by Project.status. Nothing ticked
	// means "every status", which is the state the page loads in.
	_make_project_status_filter() {
		const mount = this.$filters.find("#rm-project-status")[0];
		if (!mount) return;

		this.project_status_control = frappe.ui.form.make_control({
			parent: mount,
			only_input: true,
			render_input: true,
			df: {
				fieldtype: "MultiSelectList",
				fieldname: "project_status",
				placeholder: __("All Statuses"),
				get_data: () =>
					PROJECT_STATUSES.map((s) => ({ value: s, label: __(s), description: "" })),
				change: () => {
					this.filters.project_status = this.project_status_control.get_value() || [];
					this.refresh({ scrollToCurrent: true }); // refresh() resets selection mode
				},
			},
		});
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
	refresh(opts = {}) {
		if (this._loading) return;
		this._loading = true;
		this._destroy_sortables();

		// A reload always leaves selection mode — the grid is about to be rebuilt.
		this._selecting = false;
		this.selected_lanes.clear();

		// `scrollToCurrent` recentres on the current sprint (first load / filter
		// changes). `preserveScroll` keeps the viewport exactly where it is — used
		// after a drag-move so the board updates in place without jumping.
		if (opts.scrollToCurrent) this._scrollToCurrentNext = true;
		if (!opts.preserveScroll) this.$grid.html(this._skeleton_html());

		// Backlog loads independently of the sprint grid (its own query + render).
		this._load_backlog();

		frappe.call({
			method: API_GET,
			args: {
				project_status: JSON.stringify(this.filters.project_status || []),
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
		// Remember the viewport so re-rendering (search, drag-move) doesn't reset it.
		const scroller = this.$grid[0];
		const prevLeft = scroller ? scroller.scrollLeft : 0;
		const prevTop = scroller ? scroller.scrollTop : 0;

		const data = this.data;
		if (!data || !data.rows.length || !data.columns.length) {
			this.$grid.html(`
				<div class="rm-empty">
					<div class="rm-empty-icon">🗺️</div>
					<p>${__("No active SCRUM projects match the current filters.")}</p>
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

		// While in selection mode, lane heads carry a checkbox so a Business
		// Analyst can pick which projects "Create Missing Sprint(s)" fills. Drop any
		// remembered selection for lanes no longer on the board.
		const lane_selectable = this._selecting && this.can_create_sprint;
		const lane_keys = new Set(data.rows.map((r) => r.key));
		this.selected_lanes.forEach((k) => {
			if (!lane_keys.has(k)) this.selected_lanes.delete(k);
		});

		// --- Body rows ---
		data.rows.forEach((row) => {
			// Sub-line carries the project's Sprint Prefix (what new sprints are named
			// from) and its status. Without a prefix nothing can be planned into the
			// lane, so say that instead of leaving it blank.
			const sub = row.prefix
				? `${frappe.utils.escape_html(row.prefix)} · ${frappe.utils.escape_html(row.project_status || "")}`
				: `<span class="rm-lane-warn">${__("No Sprint Prefix")}</span>`;
			// A prefix-less project can never receive an auto-created sprint.
			const select = lane_selectable && row.prefix
				? `<input type="checkbox" class="rm-lane-select"
						data-lane="${frappe.utils.escape_html(row.key)}"
						${this.selected_lanes.has(row.key) ? "checked" : ""}
						title="${__("Include this project when creating missing sprints")}" />`
				: "";
			html += `
				<div class="rm-lanehead">
					${select}
					<div class="rm-lane-bar"></div>
					<div class="rm-lane-text">
						<a class="rm-lane-title" href="/app/project/${encodeURIComponent(row.key)}"
							title="${__("Open project")}">${frappe.utils.escape_html(row.label)}</a>
						<div class="rm-lane-sub">${sub}</div>
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

		// First load / filter changes recentre on the current sprint; everything
		// else (search, drag-move) keeps the user's current scroll position.
		if (this._scrollToCurrentNext || !this._first_render_done) {
			this._scrollToCurrentNext = false;
			this._scroll_to_current();
		} else {
			this.$grid[0].scrollLeft = prevLeft;
			this.$grid[0].scrollTop = prevTop;
		}
		this._first_render_done = true;
		this._update_create_controls();
	}

	// Enter selection mode: reveal per-project checkboxes and swap the entry button
	// for Confirm / Cancel. Re-renders the grid so lane heads get their checkboxes.
	_enter_selection_mode() {
		this._selecting = true;
		this.selected_lanes.clear();
		this._render_grid();
	}

	_exit_selection_mode() {
		this._selecting = false;
		this.selected_lanes.clear();
		this._render_grid();
	}

	// Drive the create controls from the current data + selection state:
	//   - all hidden unless some project on the board is missing a sprint;
	//   - "Create Missing Sprint(s)" shows when idle, Confirm/Cancel + hint while
	//     selecting; Confirm stays disabled until at least one project is ticked.
	_update_create_controls() {
		if (!this.$create_missing) return;
		const missing = (this.data && this.data.missing_count) || 0;
		const available = this.can_create_sprint && missing > 0;

		if (!available) this._selecting = false;
		const selecting = available && this._selecting;

		this.$create_missing.toggle(available && !selecting);
		this.$confirm_create.toggle(selecting);
		this.$cancel_create.toggle(selecting);
		this.$select_hint.toggle(selecting);

		if (selecting) {
			const n = this.selected_lanes.size;
			this.$confirm_create
				.prop("disabled", n === 0)
				.find(".rm-confirm-label")
				.text(n ? __("Confirm — {0} project(s)", [n]) : __("Confirm"));
		}
	}

	_on_create_missing() {
		const selected = [...this.selected_lanes];
		if (!selected.length) return; // Confirm is disabled without a selection

		frappe.confirm(
			__("Create Draft sprints for every missing upcoming window across the {0} selected project(s)?", [selected.length]),
			() => {
				frappe.dom.freeze(__("Creating sprints…"));
				frappe.call({
					method: API_CREATE_MISSING,
					args: {
						project_status: JSON.stringify(this.filters.project_status || []),
						lane: this.filters.lane || undefined,
						future_count: this.filters.future_count,
						lanes: JSON.stringify(selected),
					},
					callback: (r) => {
						frappe.dom.unfreeze();
						const n = (r && r.message && r.message.created_count) || 0;
						frappe.show_alert({
							message: n
								? __("Created {0} sprint(s)", [n])
								: __("No missing sprints to create"),
							indicator: n ? "green" : "blue",
						});
						this.refresh({ preserveScroll: true });
					},
					error: (err) => {
						frappe.dom.unfreeze();
						frappe.show_alert({
							message: __("Failed to create sprints: {0}", [(err && err.message) || __("see error log")]),
							indicator: "red",
						});
					},
				});
			}
		);
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
		const matched = term && (
			(cell.sprint || "").toLowerCase().includes(term) ||
			(cell.work_items || []).some((wi) => (wi.title || "").toLowerCase().includes(term))
		)
			? "rm-matched"
			: "";
		const locked = cell.status === "Completed";

		const { loose, epics } = this._group_items(cell.work_items || []);

		// Work items that belong to an Epic are grouped under a collapsible purple
		// header (collapsed by default). Loose items — those without an epic — stay
		// in a flat list below, which also serves as the cell's drop zone so a fully
		// grouped cell can still receive drag-drops without expanding an epic first.
		const epics_html = epics
			.map((g) => this._epic_group_html(g, cell.sprint, term))
			.join("");

		const visible = loose.slice(0, MAX_ITEMS_VISIBLE);
		const hidden = loose.length - visible.length;
		let loose_html = visible.map((wi) => this._item_html(wi, term)).join("");
		if (hidden > 0) {
			loose_html += `
				<button class="rm-more" data-sprint="${frappe.utils.escape_html(cell.sprint)}">
					+${hidden} ${__("more")}
				</button>`;
		}

		// A "+" next to the sprint name opens a new tab to create a Work Item with
		// this sprint prefilled. Hidden without create rights or on a Completed
		// (locked) sprint, which cannot accept new work items.
		const add_wi = this.can_create_wi && !locked
			? `<a class="rm-add-wi" href="/app/work-item/new?sprint=${encodeURIComponent(cell.sprint)}"
					target="_blank" rel="noopener"
					title="${__("Create a work item in this sprint")}"><i class="fa fa-plus"></i></a>`
			: "";

		return `
		<div class="rm-cell ${matched} ${locked ? "rm-locked" : ""}" ${this._cell_attrs(cell, row, col)}>
			<div class="rm-cell-head">
				<div class="rm-cell-head-name">
					<a class="rm-sprint-name" href="/app/sprint/${encodeURIComponent(cell.sprint)}"
						title="${__("Open sprint")}">${frappe.utils.escape_html(cell.sprint)}</a>
					${add_wi}
				</div>
				<span class="rm-badge ${status_class}">${frappe.utils.escape_html(cell.status || "—")}</span>
			</div>
			${epics.length ? `<div class="rm-epics">${epics_html}</div>` : ""}
			<div class="rm-items rm-loose" data-droppable="1">${loose_html}</div>
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
		// Dropping here auto-creates a sprint named from the project's prefix, so a
		// prefix-less project can be looked at but not planned into.
		const can_plan = this.can_write && !!row.prefix;
		const hint = can_plan
			? `<div class="rm-empty-hint">${col.is_future ? __("Drop to plan here") : __("Drop here")}</div>`
			: "";
		return `
		<div class="rm-cell rm-cell-empty ${col.is_future ? "rm-cell-future" : ""}" ${this._cell_attrs(null, row, col)}>
			<div class="rm-items" data-droppable="${can_plan ? "1" : "0"}"></div>
			${hint}
		</div>`;
	}

	// Split a cell's work items into loose items (no epic) and epic groups. Order
	// within each bucket follows the server order (story points desc); groups are
	// ordered by combined points desc so the heaviest epic surfaces first.
	_group_items(items) {
		const loose = [];
		const by_epic = new Map();
		(items || []).forEach((wi) => {
			if (!wi.epic) {
				loose.push(wi);
				return;
			}
			let g = by_epic.get(wi.epic);
			if (!g) {
				g = { epic: wi.epic, title: wi.epic_title || wi.epic, items: [], points: 0 };
				by_epic.set(wi.epic, g);
			}
			g.items.push(wi);
			g.points += flt(wi.story_points);
		});
		const epics = [...by_epic.values()].sort(
			(a, b) => b.points - a.points || a.title.localeCompare(b.title)
		);
		return { loose, epics };
	}

	// Render one collapsible epic group. Collapsed by default; expanded when the
	// user has toggled it open (remembered across refreshes) or when a search term
	// matches one of its items, so hits are never hidden inside a closed epic.
	_epic_group_html(group, sprint, term) {
		const key = `${sprint}::${group.epic}`;
		const has_hit = !!term && group.items.some((wi) => (wi.title || "").toLowerCase().includes(term));
		const expanded = this._expanded_epics.has(key) || has_hit;
		const pts = flt(group.points, 1);
		const items_html = group.items.map((wi) => this._item_html(wi, term)).join("");

		return `
		<div class="rm-epic ${expanded ? "" : "rm-epic-collapsed"}"
			data-epic="${frappe.utils.escape_html(group.epic)}" data-key="${frappe.utils.escape_html(key)}">
			<div class="rm-epic-head" role="button" tabindex="0"
				title="${__("Show / hide work items in this epic")}">
				<i class="fa fa-caret-right rm-epic-caret"></i>
				<span class="rm-item-type rm-type-epic"></span>
				<span class="rm-epic-name" title="${frappe.utils.escape_html(group.title)}">${frappe.utils.escape_html(group.title)}</span>
				<span class="rm-epic-count" title="${__("Work items in this sprint")}">${group.items.length}</span>
				<span class="rm-epic-pts" title="${__("Combined story points in this sprint")}">${pts} ${__("SP")}</span>
				<a class="rm-item-open rm-epic-open" href="/app/work-item/${encodeURIComponent(group.epic)}"
					target="_blank" rel="noopener" title="${__("Open epic")}">↗</a>
			</div>
			<div class="rm-epic-items rm-items" data-droppable="1">${items_html}</div>
		</div>`;
	}

	_item_html(wi, term) {
		const checked = wi.accepted ? "checked" : "";
		const acc_class = wi.accepted ? "rm-item-accepted" : "";
		const type_class = `rm-type-${(wi.type || "").toLowerCase().replace(/\s+/g, "-")}`;
		const highlight = term && (wi.title || "").toLowerCase().includes(term) ? "rm-item-hit" : "";
		const pts = wi.story_points ? `<span class="rm-item-pts">${wi.story_points}</span>` : "";
		// When writable, the whole card is draggable (the grip is just a cue);
		// the title is a plain span so it doesn't intercept the drag, and a small
		// ↗ icon opens the Work Item without starting a drag.
		const grip = this.can_write
			? `<span class="rm-item-drag" title="${__("Drag to another sprint")}">⠿</span>`
			: "";
		const drag_class = this.can_write ? "rm-item-draggable" : "";

		return `
		<div class="rm-item ${acc_class} ${highlight} ${drag_class}" data-name="${frappe.utils.escape_html(wi.name)}"
			title="${frappe.utils.escape_html((wi.type || "") + " · " + (wi.status || ""))}">
			${grip}
			<input type="checkbox" class="rm-check" ${checked} disabled />
			<span class="rm-item-type ${type_class}"></span>
			<span class="rm-item-title" title="${frappe.utils.escape_html(wi.title || "")}">${frappe.utils.escape_html(wi.title || wi.name)}</span>
			${pts}
			<a class="rm-item-open" href="/app/work-item/${encodeURIComponent(wi.name)}" target="_blank"
				title="${__("Open work item")}">↗</a>
		</div>`;
	}

	_bind_cell_events() {
		this.$grid.find(".rm-lane-select").on("change", (e) => {
			const lane = $(e.currentTarget).data("lane");
			if (e.currentTarget.checked) this.selected_lanes.add(lane);
			else this.selected_lanes.delete(lane);
			this._update_create_controls();
		});

		this.$grid.find(".rm-more").on("click", (e) => {
			e.preventDefault();
			e.stopPropagation();
			const sprint = $(e.currentTarget).data("sprint");
			const cell = this._find_cell_by_sprint(sprint);
			if (!cell) return;
			const term = (this.filters.search || "").trim().toLowerCase();
			const { loose } = this._group_items(cell.work_items || []);
			const $items = $(e.currentTarget).closest(".rm-loose");
			$items.html(loose.map((wi) => this._item_html(wi, term)).join(""));
			this._init_drag(); // re-init sortable to include newly shown items
		});

		// Toggle an epic group open/closed (click or keyboard). The open-epic ↗ link
		// inside the header opens the epic instead and must not toggle.
		const toggle_epic = (head) => {
			const $group = $(head).closest(".rm-epic");
			const key = $group.data("key");
			const collapsed = $group.toggleClass("rm-epic-collapsed").hasClass("rm-epic-collapsed");
			if (collapsed) this._expanded_epics.delete(key);
			else this._expanded_epics.add(key);
		};
		this.$grid.find(".rm-epic-head").on("click", (e) => {
			if ($(e.target).closest(".rm-epic-open").length) return;
			toggle_epic(e.currentTarget);
		});
		this.$grid.find(".rm-epic-head").on("keydown", (e) => {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				toggle_epic(e.currentTarget);
			}
		});
	}

	// ----------------------------------------------------------
	// Backlog panel (unassigned work items)
	// ----------------------------------------------------------
	_read_backlog_pref() {
		try {
			return (localStorage.getItem("roadmap_backlog_open") ?? "1") === "1";
		} catch (e) {
			return true;
		}
	}

	_toggle_backlog() {
		this._backlog_open = !this._backlog_open;
		try {
			localStorage.setItem("roadmap_backlog_open", this._backlog_open ? "1" : "0");
		} catch (e) { /* ignore */ }
		this._apply_backlog_state();
	}

	// Collapse/expand the left drawer. Collapsing zeroes its width so the grid
	// reflows to the full middle; the toggle button reflects the current state.
	_apply_backlog_state() {
		const open = this._backlog_open;
		if (this.$main) this.$main.toggleClass("rm-bl-collapsed", !open);
		if (this.$backlog_toggle) {
			this.$backlog_toggle
				.toggleClass("rm-active", open)
				.attr("aria-pressed", open ? "true" : "false")
				.attr("title", open ? __("Hide the backlog") : __("Show the backlog"));
		}
	}

	_load_backlog() {
		frappe.call({
			method: API_BACKLOG,
			callback: (r) => {
				this.backlog = (r && r.message) || [];
				this._render_backlog();
			},
			error: () => {
				this.backlog = [];
				this._render_backlog();
			},
		});
	}

	_render_backlog() {
		if (!this.$backlog_list) return;
		const items = this.backlog || [];
		this.$backlog_count.text(items.length);
		if (this.$backlog_toggle_count) this.$backlog_toggle_count.text(items.length);

		// Tear down the previous instance before the list HTML is replaced.
		if (this._backlog_sortable) {
			try { this._backlog_sortable.destroy(); } catch (e) { /* ignore */ }
			this._backlog_sortable = null;
		}

		if (!items.length) {
			this.$backlog_list.html(`
				<div class="rm-backlog-empty">
					<div class="rm-backlog-empty-icon">🎉</div>
					<p>${__("No unassigned work items")}</p>
				</div>`);
			return;
		}

		const term = (this.filters.search || "").trim().toLowerCase();
		this.$backlog_list.html(items.map((wi) => this._backlog_item_html(wi, term)).join(""));
		this._init_backlog_drag();
	}

	_backlog_item_html(wi, term) {
		const type = wi.type || "";
		const slug = type.toLowerCase().replace(/\s+/g, "-");
		const hit = term && (wi.title || "").toLowerCase().includes(term) ? "rm-item-hit" : "";
		const pts = wi.story_points
			? `<span class="rm-item-pts">${wi.story_points} ${__("SP")}</span>`
			: "";
		// prettyDate → short plain text ("3h", "2d"); comment_when returns HTML.
		const when = wi.modified ? frappe.datetime.prettyDate(wi.modified, true) : "";
		const grip = this.can_write
			? `<span class="rm-item-drag" title="${__("Drag onto a sprint")}">⠿</span>`
			: "";
		const drag_class = this.can_write ? "rm-item-draggable" : "";

		return `
		<div class="rm-item rm-bl-item ${drag_class} ${hit}" data-name="${frappe.utils.escape_html(wi.name)}"
			title="${frappe.utils.escape_html(type + " · " + (wi.status || ""))}">
			${grip}
			<span class="rm-item-type rm-type-${slug}"></span>
			<div class="rm-bl-body">
				<div class="rm-bl-title">${frappe.utils.escape_html(wi.title || wi.name)}</div>
				<div class="rm-bl-meta">
					<span class="rm-typebadge rm-typebadge-${slug}">${frappe.utils.escape_html(type)}</span>
					${pts}
					<span class="rm-bl-when">${frappe.utils.escape_html(when)}</span>
				</div>
			</div>
			<a class="rm-item-open" href="/app/work-item/${encodeURIComponent(wi.name)}" target="_blank"
				title="${__("Open work item")}">↗</a>
		</div>`;
	}

	// Backlog gets its own Sortable (same "roadmap" group as the cells so items
	// can be dragged straight onto a sprint) but can never receive drops.
	_init_backlog_drag() {
		if (!this.can_write) return;
		frappe.require(SORTABLE_ASSET, () => {
			const list = this.$backlog_list[0];
			if (!list || this._backlog_sortable) return;
			this._backlog_sortable = new Sortable(list, {
				group: { name: "roadmap", pull: true, put: false },
				sort: false,
				draggable: ".rm-item",
				filter: ".rm-item-open",
				preventOnFilter: false,
				forceFallback: true,
				fallbackOnBody: true,
				fallbackTolerance: 4,
				// No reflow animation: the backlog can hold hundreds of items and
				// animating every sibling on each move makes the drag stutter.
				animation: 0,
				ghostClass: "rm-drag-ghost",
				chosenClass: "rm-drag-chosen",
				dragClass: "rm-drag-active",
				// Auto-detect scroll parents so both the tall backlog list and the
				// grid scroll while dragging across them.
				scroll: true,
				scrollSensitivity: 80,
				onMove: (evt) => {
					const c = evt.to.closest(".rm-cell");
					// Over a cell → allow unless it's a Completed (locked) sprint.
					return !c || c.dataset.locked !== "1";
				},
				onEnd: (evt) => this._on_item_moved(evt),
			});
		});
	}

	// ----------------------------------------------------------
	// Drag & drop
	// ----------------------------------------------------------
	_init_drag() {
		if (!this.can_write) return;
		frappe.require(SORTABLE_ASSET, () => {
			this._destroy_sortables();
			this.$grid.find(".rm-items").each((i, list) => {
				const cell = list.closest(".rm-cell");
				const locked = !!cell && cell.dataset.locked === "1";
				const s = new Sortable(list, {
					group: {
						name: "roadmap",
						// Items in a Completed sprint are frozen — can't be dragged out.
						pull: locked ? false : true,
						// Allow drop only into non-completed, droppable cells.
						put: (to) => {
							const c = to.el.closest(".rm-cell");
							return (
								!!c &&
								c.dataset.locked !== "1" &&
								to.el.getAttribute("data-droppable") === "1"
							);
						},
					},
					sort: false,
					draggable: ".rm-item",
					// Let the open-icon and checkbox handle their own clicks.
					filter: ".rm-item-open, .rm-check",
					preventOnFilter: false,
					// Use SortableJS's own drag engine — native HTML5 DnD is unreliable
					// inside this scrollable, sticky-header grid (drops snap back).
					forceFallback: true,
					fallbackOnBody: true,
					fallbackTolerance: 4,
					animation: 150,
					ghostClass: "rm-drag-ghost",
					chosenClass: "rm-drag-chosen",
					dragClass: "rm-drag-active",
					scroll: this.$grid[0],
					scrollSensitivity: 80,
					onMove: (evt) => {
						const c = evt.to.closest(".rm-cell");
						return !!c && c.dataset.locked !== "1";
					},
					onEnd: (evt) => this._on_item_moved(evt),
				});
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
				this.refresh({ preserveScroll: true });
			},
			error: (err) => {
				frappe.dom.unfreeze();
				frappe.show_alert({
					message: __("Move failed: {0}", [(err && err.message) || __("see error log")]),
					indicator: "red",
				});
				this.refresh({ preserveScroll: true }); // reload in place to restore positions
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

	_backlog_skeleton_html() {
		return `<div class="rm-backlog-skeleton">${Array(5).fill('<div class="rm-skel-line"></div>').join("")}</div>`;
	}
}
