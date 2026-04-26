// Copyright (c) 2026, One FM and contributors
// For license information, please see license.txt

// Work Items Priority Page
// Provides a drag-and-drop interface to locally reorder Work Items
// from active sprints. Ordering is stored in localStorage — each
// team member maintains their own view without server writes.

const PAGE_SIZE = 50;
const STORAGE_KEY_PREFIX = "wi_priority_order_";
const SORTABLE_ASSET = "/assets/frappe_agile/js/vendor/sortable.min.js";

frappe.pages["priority-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Priority Board"),
		single_column: true,
	});

	// Attach the controller
	wrapper.priority_board_page = new PriorityBoardPage(page, wrapper);
};

frappe.pages["priority-board"].on_page_show = function (wrapper) {
	// Refresh data when navigating back to the page
	if (wrapper.priority_board_page) {
		wrapper.priority_board_page.refresh();
	}
};

// =========================================================
// PriorityBoardPage Controller
// =========================================================
class PriorityBoardPage {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;

		// State
		this.all_items = [];       // full fetched list (before local order)
		this.ordered_items = [];   // after applying local order
		this.displayed_count = 0;
		this.filters = {
			sprint: "",
			status: "",
			priority: "",
			assignee: "",
		};
		this.can_write = false;
		this.sortable = null;
		this._loading = false;

		// Build UI skeleton, then load
		this._check_permission().then(() => {
			this._build_ui();
			this._load_sprints().then(() => {
				this.refresh();
			});
		});
	}

	// ----------------------------------------------------------
	// Permission check
	// ----------------------------------------------------------
	_check_permission() {
		return new Promise((resolve) => {
			this.can_write = frappe.model.can_write("Work Item");
			resolve();
		});
	}

	// ----------------------------------------------------------
	// Build HTML structure
	// ----------------------------------------------------------
	_build_ui() {
		const $body = $(this.page.body);
		$body.empty();

		// Main wrapper
		$body.append(`
			<div class="wi-page-wrapper">
				<div class="wi-filters-bar" id="wi-filters-bar"></div>
				<div class="wi-header-strip" id="wi-header-strip"></div>
				<div class="wi-list-container" id="wi-list-container">
					${this._skeleton_html(6)}
				</div>
			</div>
		`);

		this.$filters = $body.find("#wi-filters-bar");
		this.$header  = $body.find("#wi-header-strip");
		this.$list    = $body.find("#wi-list-container");

		this._render_filters();
	}

	// ----------------------------------------------------------
	// Filters bar
	// ----------------------------------------------------------
	_render_filters() {
		this.$filters.html(`
			<div class="wi-filter-group" id="wi-filter-sprint">
				<span class="wi-filter-label">${__("Sprint")}</span>
			</div>
			<div class="wi-filter-group">
				<span class="wi-filter-label">${__("Status")}</span>
				<select id="wi-sel-status" class="form-control input-xs">
					<option value="">${__("All Statuses")}</option>
					<option value="Open">${__("Open")}</option>
					<option value="In Progress">${__("In Progress")}</option>
					<option value="Pending Action Plan">${__("Pending Action Plan")}</option>
					<option value="Pending Execution">${__("Pending Execution")}</option>
					<option value="Pending PR">${__("Pending PR")}</option>
					<option value="Pending Review">${__("Pending Review")}</option>
					<option value="Changes Requested">${__("Changes Requested")}</option>
					<option value="In Staging">${__("In Staging")}</option>
					<option value="Rejected">${__("Rejected")}</option>
					<option value="Done">${__("Done")}</option>
				</select>
			</div>
			<div class="wi-filter-group">
				<span class="wi-filter-label">${__("Priority")}</span>
				<select id="wi-sel-priority" class="form-control input-xs">
					<option value="">${__("All Priorities")}</option>
					<option value="Highest">${__("Highest")}</option>
					<option value="High">${__("High")}</option>
					<option value="Medium">${__("Medium")}</option>
					<option value="Low">${__("Low")}</option>
					<option value="Lowest">${__("Lowest")}</option>
				</select>
			</div>
			<div class="wi-filter-group" id="wi-filter-assignee">
				<span class="wi-filter-label">${__("Assignee")}</span>
			</div>
			<div class="wi-filters-actions">
				${!this.can_write ? `
					<span class="wi-read-only-notice">
						<i class="fa fa-lock"></i> ${__("Read-only — no write permission")}
					</span>
				` : ""}
				<button class="btn btn-default btn-xs" id="wi-btn-reset-order">
					<i class="fa fa-undo"></i> ${__("Reset Order")}
				</button>
				<button class="btn btn-primary btn-xs" id="wi-btn-refresh">
					<i class="fa fa-refresh"></i> ${__("Refresh")}
				</button>
			</div>
		`);

		// Sprint link field (frappe-style)
		// df.change is used instead of $input.on("change") because Frappe's
		// Link control fires df.change (not the native DOM change event) when
		// the user picks a value from the autocomplete dropdown.
		this._sprint_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "sprint",
				options: "Sprint",
				placeholder: __("All Active Sprints"),
				change: () => {
					this.filters.sprint = this._sprint_field.get_value() || "";
					this.refresh();
				},
			},
			parent: this.$filters.find("#wi-filter-sprint"),
			render_input: true,
		});
		this._sprint_field.$input.addClass("input-xs");
		this._sprint_field.$input.css("height", "32px");

		// Assignee link field
		this._assignee_field = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "assignee",
				options: "User",
				placeholder: __("All Assignees"),
				change: () => {
					this.filters.assignee = this._assignee_field.get_value() || "";
					this.refresh();
				},
			},
			parent: this.$filters.find("#wi-filter-assignee"),
			render_input: true,
		});
		this._assignee_field.$input.addClass("input-xs");
		this._assignee_field.$input.css("height", "32px");
		this.$filters.find("#wi-sel-status").on("change", (e) => {
			this.filters.status = e.target.value;
			this.refresh();
		});
		this.$filters.find("#wi-sel-priority").on("change", (e) => {
			this.filters.priority = e.target.value;
			this.refresh();
		});
		this.$filters.find("#wi-btn-refresh").on("click", () => this.refresh());
		this.$filters.find("#wi-btn-reset-order").on("click", () => this._reset_local_order());
	}

	// ----------------------------------------------------------
	// Load sprint options (used for validation only here)
	// ----------------------------------------------------------
	_load_sprints() {
		return new Promise((resolve) => {
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Sprint",
					filters: { status: "Active" },
					fields: ["name"],
					limit_page_length: 200,
				},
				callback: (r) => {
					this.active_sprints = r.message ? r.message.map(s => s.name) : [];
					resolve();
				},
				error: () => {
					this.active_sprints = [];
					resolve();
				},
			});
		});
	}

	// ----------------------------------------------------------
	// Main refresh — fetch data from server
	// ----------------------------------------------------------
	refresh() {
		if (!this.$list || this._loading) return;
		this._loading = true;
		this.$list.html(this._skeleton_html(6));

		const f = frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Work Item",
				filters: this._build_server_filters(),
				fields: [
					"name", "title", "status", "priority",
					"assignee_user", "story_points", "sprint",
					"work_item_type",
				],
				limit_page_length: 2000,
				order_by: "modified desc",
			},
			callback: (r) => {
				this._loading = false;
				if (r && r.message) {
					this.all_items = r.message;
					this._apply_filters_and_render();
				} else {
					this._show_empty(__("No Work Items found"));
				}
			},
			error: (err) => {
				this._loading = false;
				frappe.msgprint({
					title: __("Error"),
					message: __("Failed to load Work Items: ") + (err && err.message ? err.message : ""),
					indicator: "red",
				});
				this._show_empty(__("Failed to load data. Please refresh."));
			},
		});

		return f;
	}

	// ----------------------------------------------------------
	// Build server-side filters
	// ----------------------------------------------------------
	_build_server_filters() {
		const filters = {};

		// Only items in sprints (exclude Epics without sprints)
		// We always limit to items that have a sprint assigned
		if (this.filters.sprint) {
			filters["sprint"] = this.filters.sprint;
		} else if (this.active_sprints && this.active_sprints.length > 0) {
			// Fetch only items in active sprints
			filters["sprint"] = ["in", this.active_sprints];
		} else {
			filters["sprint"] = "___NONE___"; // no active sprints
		}

		if (this.filters.status)   filters["status"]        = this.filters.status;
		if (this.filters.priority) filters["priority"]       = this.filters.priority;
		if (this.filters.assignee) filters["assignee_user"]  = this.filters.assignee;

		return filters;
	}

	// ----------------------------------------------------------
	// Apply local order + render
	// ----------------------------------------------------------
	_apply_filters_and_render() {
		const storage_key = this._storage_key();
		const saved_order = this._load_local_order(storage_key);

		if (saved_order && saved_order.length) {
			// Re-order all_items according to the saved order
			const order_map = {};
			saved_order.forEach((name, idx) => { order_map[name] = idx; });

			this.ordered_items = [...this.all_items].sort((a, b) => {
				const ia = order_map[a.name] !== undefined ? order_map[a.name] : 9999;
				const ib = order_map[b.name] !== undefined ? order_map[b.name] : 9999;
				return ia - ib;
			});
		} else {
			this.ordered_items = [...this.all_items];
		}

		this.displayed_count = 0;
		this._render_list();
	}

	// ----------------------------------------------------------
	// Render the list
	// ----------------------------------------------------------
	_render_list() {
		this.$list.empty();

		if (!this.ordered_items.length) {
			this._show_empty(__("No Work Items match current filters"));
			return;
		}

		// Header strip
		const total = this.ordered_items.length;
		const showing = Math.min(PAGE_SIZE, total);
		this.$header.html(`
			<strong>${total}</strong>&nbsp;${__("items")}
			&nbsp;·&nbsp;${__("Showing")} <strong>${showing}</strong>
			<span class="wi-local-badge">
				<i class="fa fa-user"></i>&nbsp;${__("Local order — not shared")}
			</span>
		`);

		// Items list
		const $ul = $(`<div class="wi-sortable-list" id="wi-sortable-list"></div>`);
		this.$list.append($ul);

		const page_items = this.ordered_items.slice(0, PAGE_SIZE);
		page_items.forEach((item, idx) => {
			$ul.append(this._card_html(item, idx + 1));
		});
		this.displayed_count = page_items.length;

		// Load more
		if (total > PAGE_SIZE) {
			const remaining = total - PAGE_SIZE;
			this.$list.append(`
				<div class="wi-load-more-wrap">
					<button class="btn btn-default btn-sm" id="wi-load-more">
						${__("Load {0} more", [Math.min(remaining, PAGE_SIZE)])}
					</button>
				</div>
			`);
			this.$list.find("#wi-load-more").on("click", () => this._load_more($ul));
		}

		// Initialise drag-and-drop
		frappe.require(SORTABLE_ASSET, () => {
			this._init_sortable($ul[0]);
		});
	}

	// ----------------------------------------------------------
	// Lazy load more items
	// ----------------------------------------------------------
	_load_more($ul) {
		const start = this.displayed_count;
		const next_batch = this.ordered_items.slice(start, start + PAGE_SIZE);
		const remaining_after = this.ordered_items.length - start - next_batch.length;

		next_batch.forEach((item, i) => {
			$ul.append(this._card_html(item, start + i + 1));
		});
		this.displayed_count += next_batch.length;

		// Update header
		this.$header.find("strong").last().text(this.displayed_count);

		// Update or hide load-more button
		const $btn = this.$list.find("#wi-load-more");
		if (remaining_after > 0) {
			$btn.text(__("Load {0} more", [Math.min(remaining_after, PAGE_SIZE)]));
		} else {
			$btn.closest(".wi-load-more-wrap").remove();
		}

		// Re-init sortable to cover newly added nodes
		frappe.require(SORTABLE_ASSET, () => {
			this._init_sortable($ul[0]);
		});
	}

	// ----------------------------------------------------------
	// Card HTML
	// ----------------------------------------------------------
	_card_html(item, position) {
		const priority_color = this._priority_color((item.priority || "medium").toLowerCase());
		const status_label   = item.status || "—";
		const status_class   = this._status_class(item.status);
		const points_html    = item.story_points
			? `<span class="wi-badge wi-badge-points">${flt(item.story_points, 1)} pts</span>`
			: "";
		const assignee_html  = item.assignee_user
			? `<span class="wi-assignee">
				<span class="wi-assignee-avatar">${this._initials(item.assignee_user)}</span>
				<span class="wi-assignee-name">${frappe.utils.escape_html(item.assignee_user.split("@")[0].replace(".", " ").replace(/\b\w/g, c => c.toUpperCase()))}</span>
			   </span>`
			: `<span class="wi-assignee wi-assignee-none">${__("Unassigned")}</span>`;

		const drag_handle = this.can_write
			? `<div class="wi-drag-handle wi-drag-handle-icon" title="${__("Drag to reorder")}">
				<svg xmlns="http://www.w3.org/2000/svg" height="20" viewBox="0 0 24 24" width="20" fill="currentColor">
					<path d="M0 0h24v24H0z" fill="none"/>
					<path d="M11 18c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2 2 .9 2 2zm-2-8c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 4c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
				</svg>
			   </div>`
			: `<div class="wi-drag-handle wi-drag-handle-disabled">
				<svg xmlns="http://www.w3.org/2000/svg" height="20" viewBox="0 0 24 24" width="20" fill="currentColor">
					<path d="M0 0h24v24H0z" fill="none"/>
					<path d="M11 18c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2 2 .9 2 2zm-2-8c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 4c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
				</svg>
			   </div>`;

		const no_drag_class = this.can_write ? "" : "no-drag";

		return `
		<div class="wi-card ${no_drag_class}" data-name="${frappe.utils.escape_html(item.name)}">
			<div class="wi-card-pos">
				<span class="wi-position-badge" style="color:${priority_color}">#${position}</span>
			</div>
			<div class="wi-card-body">
				<div class="wi-card-top">
					<span class="wi-card-id">${frappe.utils.escape_html(item.name)}</span>
					<span class="wi-card-title">
						<a href="/app/work-item/${encodeURIComponent(item.name)}" target="_blank">
							${frappe.utils.escape_html(item.title || "—")}
						</a>
					</span>
				</div>
				<div class="wi-card-meta">
					<span class="wi-badge wi-badge-status ${status_class}">${frappe.utils.escape_html(status_label)}</span>
					${points_html}
					${assignee_html}
				</div>
			</div>
			${drag_handle}
		</div>`;
	}

	// ----------------------------------------------------------
	// SortableJS init
	// ----------------------------------------------------------
	_init_sortable(el) {
		if (!el) return;

		// Destroy existing instance
		if (this.sortable) {
			this.sortable.destroy();
			this.sortable = null;
		}

		if (!this.can_write) return;

		this.sortable = new Sortable(el, {
			animation: 150,
			handle: ".wi-drag-handle-icon",
			ghostClass: "sortable-ghost",
			chosenClass: "sortable-chosen",
			dragClass: "sortable-drag",
			forceFallback: false,

			onEnd: (evt) => {
				this._on_reorder(evt, el);
			},
		});
	}

	// ----------------------------------------------------------
	// Handle reorder
	// ----------------------------------------------------------
	_on_reorder(evt, el) {
		const { oldIndex, newIndex } = evt;
		if (oldIndex === newIndex) return;

		// Move item in ordered_items array (only for displayed items)
		const displayed = this.ordered_items.slice(0, this.displayed_count);
		const rest      = this.ordered_items.slice(this.displayed_count);

		const [moved] = displayed.splice(oldIndex, 1);
		displayed.splice(newIndex, 0, moved);
		this.ordered_items = [...displayed, ...rest];

		// Update position badges
		$(el).find(".wi-card").each((i, card) => {
			$(card).find(".wi-card-pos .wi-position-badge").text(`#${i + 1}`);
		});

		// Persist to localStorage
		this._save_local_order();
	}

	// ----------------------------------------------------------
	// localStorage helpers
	// ----------------------------------------------------------
	_storage_key() {
		// Key is per user + sprint filter so different sprints get separate orderings
		const user   = frappe.session.user;
		const sprint = this.filters.sprint || "all";
		return `${STORAGE_KEY_PREFIX}${user}_${sprint}`;
	}

	_save_local_order() {
		const key   = this._storage_key();
		const names = this.ordered_items.map((i) => i.name);
		try {
			localStorage.setItem(key, JSON.stringify(names));
		} catch (e) {
			// localStorage quota exceeded — silently ignore
		}
	}

	_load_local_order(key) {
		try {
			const raw = localStorage.getItem(key);
			return raw ? JSON.parse(raw) : null;
		} catch (e) {
			return null;
		}
	}

	_reset_local_order() {
		frappe.confirm(
			__("Reset your local ordering for the current filters? This cannot be undone."),
			() => {
				try {
					localStorage.removeItem(this._storage_key());
				} catch (e) {
					// ignore
				}
				this._apply_filters_and_render();
				frappe.show_alert({ message: __("Order reset to default"), indicator: "green" });
			}
		);
	}

	// ----------------------------------------------------------
	// Helpers
	// ----------------------------------------------------------
	_skeleton_html(count) {
		return Array(count).fill('<div class="wi-skeleton-card"></div>').join("");
	}

	_show_empty(msg) {
		this.$list.html(`
			<div class="wi-empty-state">
				<div class="wi-empty-icon">📋</div>
				<p>${frappe.utils.escape_html(msg)}</p>
			</div>
		`);
		this.$header.html("");
	}

	_initials(user) {
		if (!user) return "?";
		const parts = user.split("@")[0].split(".");
		return parts.map((p) => p[0] || "").join("").toUpperCase().slice(0, 2);
	}

	_priority_color(priority) {
		const map = {
			highest: "#ef4444",
			high:    "#f97316",
			medium:  "#eab308",
			low:     "#3b82f6",
			lowest:  "#94a3b8",
		};
		return map[priority] || "#94a3b8";
	}

	_status_class(status) {
		const map = {
			"Open":                 "wi-status-open",
			"In Progress":          "wi-status-in-progress",
			"Pending Action Plan":  "wi-status-pending-action",
			"Pending Execution":    "wi-status-pending-exec",
			"Pending PR":           "wi-status-pending-pr",
			"Pending Review":       "wi-status-pending-review",
			"Changes Requested":    "wi-status-changes",
			"In Staging":           "wi-status-staging",
			"Rejected":             "wi-status-rejected",
			"Done":                 "wi-status-done",
		};
		return map[status] || "";
	}
}
