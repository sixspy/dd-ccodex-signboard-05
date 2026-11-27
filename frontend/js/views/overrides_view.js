window.SB_VIEWS = window.SB_VIEWS || {};
window.SB_VIEWS["overrides-view"] = {
  template: `
  <div class="panel">
    <h2>单屏覆盖</h2>
    <p class="lead">临时强制清单 / 空屏 / 单素材，求值优先于正式发布；紧急撤屏会同事务级联停用并同票落痕。</p>
    <div class="row-form">
      <input v-model.number="form.screen_id" type="number" placeholder="屏幕ID" />
      <select v-model="form.effect">
        <option value="force_blank">强制空屏</option>
        <option value="force_playlist">强制清单</option>
        <option value="force_asset">强制单素材</option>
      </select>
      <input v-model.number="form.playlist_id" type="number" placeholder="清单ID(可选)" />
      <input v-model.number="form.asset_id" type="number" placeholder="素材ID(可选)" />
      <button class="primary" @click="create">正式覆盖</button>
    </div>
    <p class="err" v-if="error">{{ error }}</p>
    <table>
      <thead><tr><th>ID</th><th>屏幕</th><th>效果</th><th>生效</th><th>备注</th></tr></thead>
      <tbody>
        <tr v-for="o in items" :key="o.id">
          <td>{{ o.id }}</td><td>{{ o.screen_code }}</td><td>{{ o.effect }}</td>
          <td><span class="badge" :class="o.active ? 'warn' : 'bad'">{{ o.active ? "生效" : "已停用" }}</span></td>
          <td>{{ o.note || "—" }}</td>
        </tr>
      </tbody>
    </table>
    <h3>撤屏级联停用记录（同票）</h3>
    <table>
      <thead><tr><th>ID</th><th>覆盖</th><th>详情</th><th>操作者</th></tr></thead>
      <tbody>
        <tr v-for="c in cascades" :key="c.id"><td>{{ c.id }}</td><td>override#{{ c.entity_id }}</td><td>{{ c.detail }}</td><td>{{ c.actor }}</td></tr>
        <tr v-if="!cascades.length"><td colspan="4" class="hint">暂无级联停用</td></tr>
      </tbody>
    </table>
  </div>`,
  data() { return { items: [], cascades: [], error: "", form: { screen_id: 1, effect: "force_blank", playlist_id: null, asset_id: null, note: "" } }; },
  async mounted() { await this.reload(); },
  methods: {
    async reload() {
      this.items = (await SB.api("/api/overrides")).items;
      const hist = (await SB.api("/api/history?limit=300")).items;
      this.cascades = hist.filter(h => h.action === "panic_cascade_off");
    },
    async create() {
      this.error = "";
      const body = { ...this.form };
      if (body.effect === "force_blank") { body.playlist_id = null; body.asset_id = null; }
      try {
        await SB.api("/api/overrides/official", { method: "POST", body: JSON.stringify(body) });
        await this.reload();
      } catch (e) { this.error = e.message; }
    }
  }
};
