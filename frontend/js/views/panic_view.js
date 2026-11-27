window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["panic-view"] = {
  template: `
  <div class="panel">
    <h2>紧急撤屏</h2>
    <p class="lead">正式撤屏同事务级联停用该屏活跃覆盖，同票双痕；甲乙两路不混用，并发抢「同屏撤屏级联互斥」。</p>
    <div class="row-form">
      <input v-model.number="screen_id" type="number" placeholder="屏幕ID" />
      <input v-model="reason" placeholder="原因" />
      <button class="danger" @click="official">正式撤屏</button>
      <button class="ghost" @click="shadow">影子撤屏</button>
      <input v-model.number="shadowId" type="number" placeholder="影子ID" />
      <button class="primary" @click="promote">升正</button>
    </div>
    <p v-if="last" class="hint">
      撤屏完成：<span class="badge">{{ last.ticket }}</span>
      级联停用覆盖 <span class="badge warn">{{ last.cascaded_overrides }} 条</span>
    </p>
    <p class="err" v-if="error">
      <span v-if="isContention" class="badge warn">争用</span> {{ error }}
    </p>
    <h3>撤屏事件</h3>
    <table>
      <thead><tr><th>ID</th><th>屏幕</th><th>原因</th><th>操作者</th></tr></thead>
      <tbody>
        <tr v-for="e in items" :key="e.id"><td>{{ e.id }}</td><td>{{ e.screen_code }}</td><td>{{ e.reason }}</td><td>{{ e.created_by }}</td></tr>
      </tbody>
    </table>
    <h3>争用记录（败方零正式，只记争用）</h3>
    <table>
      <thead><tr><th>ID</th><th>屏幕</th><th>详情</th><th>操作者</th></tr></thead>
      <tbody>
        <tr v-for="c in contentions" :key="c.id"><td>{{ c.id }}</td><td>{{ c.entity_id }}</td><td>{{ c.detail }}</td><td>{{ c.actor }}</td></tr>
        <tr v-if="!contentions.length"><td colspan="4" class="hint">暂无争用</td></tr>
      </tbody>
    </table>
  </div>`,
  data() { return { items: [], contentions: [], screen_id: 1, reason: "内容异常", shadowId: null, error: "", last: null }; },
  computed: {
    isContention() { return this.error.includes("争用"); }
  },
  async mounted() { await this.reload(); },
  methods: {
    async reload() {
      this.items = (await SB.api("/api/panic/events")).items;
      const hist = (await SB.api("/api/history?limit=300")).items;
      this.contentions = hist.filter(h => h.action === "panic_cascade_contention");
    },
    async official() {
      this.error = ""; this.last = null;
      try {
        this.last = await SB.api("/api/panic/official", { method: "POST", body: JSON.stringify({ screen_id: this.screen_id, reason: this.reason }) });
        await this.reload();
      } catch (e) { this.error = e.message; }
    },
    async shadow() {
      this.error = ""; this.last = null;
      try {
        const r = await SB.api("/api/panic/shadow", { method: "POST", body: JSON.stringify({ screen_id: this.screen_id, reason: this.reason }) });
        this.shadowId = r.id;
      } catch (e) { this.error = e.message; }
    },
    async promote() {
      this.error = ""; this.last = null;
      try {
        this.last = await SB.api("/api/panic/shadow/" + this.shadowId + "/promote", { method: "POST", body: "{}" });
        await this.reload();
      } catch (e) { this.error = e.message; }
    }
  }
};
