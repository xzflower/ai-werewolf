<template>
  <div class="app-container">
    <!-- 顶栏 -->
    <header class="app-header">
      <h1>🐺 AI <span>狼人杀</span></h1>
      <div v-if="gs.phase !== 'lobby'" class="phase-badge">
        <span class="phase-dot" :class="phaseDotClass"></span>
        {{ phaseLabel }}
        <span v-if="gs.round > 0" style="color:var(--text-dim);margin-left:4px">第{{ gs.round }}轮</span>
      </div>
      <div v-if="gs.phase !== 'lobby'" style="font-size:12px;color:var(--text-dim)">
        <span style="color:var(--good-green)">● {{ gs.aliveCount }}</span>
        <span style="color:var(--evil-red);margin-left:8px">● {{ gs.wolfCount }}</span>
      </div>
    </header>

    <!-- 开始界面 -->
    <div v-if="gs.phase === 'lobby'" class="start-screen" style="grid-column:1/-1;grid-row:2">
      <div class="logo">🐺</div>
      <h2>AI 狼人杀</h2>
      <p style="color:var(--text-secondary);max-width:400px;text-align:center">
        12 名 AI 驱动的智能体在信息不对称约束下进行
        协作、对抗与博弈的经典狼人杀对局
      </p>
      <button class="start-btn" @click="startGame" :disabled="loading">
        {{ loading ? '⏳ 创建游戏中...' : '🎮 开始观战' }}
      </button>
    </div>

    <!-- 左侧：玩家列表 -->
    <aside v-if="gs.phase !== 'lobby'" class="sidebar-left">
      <div class="panel-title">👥 玩家 ({{ gs.players.filter(p => p.alive).length }}/{{ gs.players.length }})</div>
      <div v-for="p in gs.players" :key="p.id" class="player-card" :class="{ dead: !p.alive }">
        <div class="player-avatar" :style="{ background: playerColor(p.id) }">
          {{ p.id }}
        </div>
        <div class="player-info">
          <div class="player-name">{{ p.name }}</div>
          <div v-if="!p.alive" class="player-role revealed">{{ roleLabel(p.role) }}</div>
        </div>
        <div class="player-status" :class="p.alive ? 'status-alive' : 'status-dead'">
          {{ p.alive ? '存活' : '死亡' }}
        </div>
      </div>
    </aside>

    <!-- 主区域：事件时间线 -->
    <main v-if="gs.phase !== 'lobby'" class="main-area" ref="timelineRef">
      <div class="event-timeline">
        <div v-for="(evt, i) in gs.eventLog" :key="i"
             class="event-entry"
             :class="eventClass(evt)">
          <div class="event-label">{{ evt.label }}</div>
          <div class="event-content" v-if="evt.type === 'speech'">
            <strong>{{ evt.data.player_name }}</strong>：{{ evt.data.content }}
            <div v-if="evt.data.inner_monologue" class="inner-mono">
              💭 {{ evt.data.inner_monologue }}
            </div>
          </div>
          <div class="event-content" v-else-if="evt.type === 'vote_result'">
            <div v-for="(target, voter) in evt.data.votes" :key="voter" class="vote-bar">
              <span class="voter-label">{{ playerName(Number(voter)) }}</span>
              <div class="vote-fill" :style="voteBarStyle(target, gs.players.length)">
                🗳 {{ playerName(target) }}
              </div>
            </div>
          </div>
          <div class="event-content" v-else-if="evt.type === 'elimination'">
            ⚰️ <strong>{{ evt.data.player_name }}</strong>
            <span :style="{color: evt.data.role === 'werewolf' ? 'var(--evil-red)' : 'var(--accent)', fontWeight: 600}">
              ({{ roleLabel(evt.data.role) }})
            </span>
            — {{ causeLabel(evt.data.cause) }}
          </div>
          <div class="event-content" v-else-if="evt.type === 'night_result'">
            <div v-if="evt.data.deaths && evt.data.deaths.length">
              <div v-for="d in evt.data.deaths" :key="d.player_id">
                💀 <strong>{{ d.player_name }}</strong>
                <span :style="{color: d.role === 'werewolf' ? 'var(--evil-red)' : 'var(--text-dim)'}">
                  ({{ roleLabel(d.role) }})
                </span>
                — {{ causeLabel(d.cause) }}
              </div>
            </div>
            <div v-else>🌙 平安夜，无人死亡</div>
          </div>
          <div class="event-content" v-else-if="evt.type === 'seer_result'">
            🔮 查验 玩家{{ evt.data.target_id }}({{ evt.data.target_name }})
            → {{ evt.data.camp === 'werewolf' ? '🐺 狼人' : '👼 好人' }}
          </div>
          <div class="event-content" v-else-if="evt.type === 'wolf_chat'">
            🐺 <strong>玩家{{ evt.data.player_id }}</strong>：{{ evt.data.content }}
          </div>
          <div class="event-content" v-else-if="evt.type === 'game_over'">
            🏁 <strong>{{ evt.data.winner === 'werewolf' ? '🐺 狼人阵营获胜！' : '👼 好人阵营获胜！' }}</strong>
          </div>
          <div class="event-content" v-else-if="evt.type === 'phase_change'">
            {{ phaseIcon(evt.data.phase) }} 阶段切换至：{{ phaseLabelFor(evt.data.phase) }}
          </div>
          <div class="event-content" v-else>
            {{ JSON.stringify(evt.data) }}
          </div>
        </div>
      </div>
    </main>

    <!-- 右侧：状态面板 -->
    <aside v-if="gs.phase !== 'lobby'" class="sidebar-right">
      <!-- 统计数据 -->
      <div class="panel-section">
        <div class="panel-title">📊 统计</div>
        <div class="stat-row">
          <span class="stat-label">当前轮次</span>
          <span class="stat-value">{{ gs.round }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">存活人数</span>
          <span class="stat-value" style="color:var(--good-green)">{{ gs.aliveCount }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">狼人存活</span>
          <span class="stat-value" style="color:var(--evil-red)">{{ gs.wolfCount }}</span>
        </div>
        <div class="stat-row">
          <span class="stat-label">已出局</span>
          <span class="stat-value" style="color:var(--text-dim)">{{ gs.eliminationHistory.length }}</span>
        </div>
      </div>

      <!-- 死亡记录 -->
      <div v-if="gs.eliminationHistory.length" class="panel-section">
        <div class="panel-title">⚰️ 出局记录</div>
        <div v-for="(e, i) in gs.eliminationHistory" :key="i" style="font-size:13px;padding:3px 0;border-bottom:1px solid var(--border)">
          <span v-if="e.cause === 'werewolf_kill'">🐺</span>
          <span v-else-if="e.cause === 'vote'">🗳</span>
          <span v-else-if="e.cause === 'poison'">☠️</span>
          <span v-else-if="e.cause === 'hunter_shot'">🏹</span>
          <span v-else>💀</span>
          {{ e.player_name }}
          <span style="color:var(--text-dim);font-size:11px">({{ roleLabel(e.role) }})</span>
        </div>
      </div>

      <!-- 预言家记录 -->
      <div v-if="gs.seerResults.length" class="panel-section">
        <div class="panel-title">🔮 预言家查验</div>
        <div v-for="(r, i) in gs.seerResults" :key="i" style="font-size:13px;padding:3px 0;border-bottom:1px solid var(--border)">
          第{{ r.round }}轮：玩家{{ r.targetId }}
          <span :style="{color: r.camp === 'werewolf' ? 'var(--evil-red)' : 'var(--good-green)'}">
            → {{ r.camp === 'werewolf' ? '狼人' : '好人' }}
          </span>
        </div>
      </div>
    </aside>

    <!-- Game Over 弹窗 -->
    <div v-if="gs.gameOver" class="game-over-overlay" @click="resetGame">
      <div class="result-icon">{{ gs.winner === 'werewolf' ? '🐺' : '👼' }}</div>
      <div class="result-text" :class="gs.winner === 'werewolf' ? 'wolf' : 'villager'">
        {{ gs.winner === 'werewolf' ? '狼人阵营获胜' : '好人阵营获胜' }}
      </div>
      <p style="color:var(--text-secondary)">{{ gs.eliminationHistory.length }} 人出局，共 {{ gs.round }} 轮</p>
      <button class="start-btn" style="margin-top:16px" @click="resetGame">🔄 再来一局</button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'
import { useWebSocket } from './composables/useWebSocket.js'
import { useGameState } from './composables/useGameState.js'

const { state: gs, phaseLabel, processEvent, reset } = useGameState()
const { connect, disconnect, drainEvents } = useWebSocket()
const loading = ref(false)
const timelineRef = ref(null)

const colors = [
  '#0ea5e9', '#8b5cf6', '#06b6d4', '#14b8a6',
  '#10b981', '#84cc16', '#eab308', '#f97316',
  '#ef4444', '#ec4899', '#6366f1', '#a855f7',
]

function playerColor(id) {
  return colors[(id - 1) % colors.length] + '33'
}

function playerName(id) {
  const p = gs.players.find(p => p.id === id)
  return p ? p.name : `玩家${id}`
}

function roleLabel(role) {
  const labels = {
    werewolf: '狼人', seer: '预言家', witch: '女巫',
    hunter: '猎人', guard: '守卫', villager: '村民',
  }
  return labels[role] || role
}

function causeLabel(cause) {
  const labels = {
    werewolf_kill: '被狼人击杀', vote: '被投票放逐',
    poison: '被毒杀', hunter_shot: '被猎人带走',
  }
  return labels[cause] || cause
}

function phaseIcon(phase) {
  const icons = {
    night_werewolf: '🐺', night_seer: '🔮', night_witch: '🧪',
    night_guard: '🛡️', day_speech: '☀️', day_vote: '🗳',
    hunter_shot: '🏹', game_over: '🏁',
  }
  return icons[phase] || '📌'
}

function phaseLabelFor(phase) {
  const labels = {
    night_werewolf: '狼人行动', night_seer: '预言家查验',
    night_witch: '女巫行动', night_guard: '守卫守护',
    day_announce: '天亮公告', day_speech: '白天发言',
    day_vote: '投票', vote_result: '投票结果',
    hunter_shot: '猎人开枪', game_over: '游戏结束',
  }
  return labels[phase] || phase
}

function voteBarStyle(targetId, max) {
  const count = Object.values(gs.currentVotes).filter(v => v === targetId).length
  const pct = Math.max(count / max * 100, 2)
  return {
    width: pct + '%',
    background: targetId === 0 ? 'var(--text-dim)' : 'var(--accent-dim)',
  }
}

const phaseDotClass = ref('night')
watch(() => gs.phase, (p) => {
  if (p.startsWith('night')) phaseDotClass.value = 'night'
  else if (p === 'day_speech') phaseDotClass.value = 'day'
  else if (p.startsWith('day') || p === 'vote_result') phaseDotClass.value = 'vote'
})

function eventClass(evt) {
  if (evt.type === 'speech') return 'speech'
  if (evt.type === 'vote_result') return 'vote'
  if (evt.type === 'elimination' || evt.type === 'night_result') return 'death'
  if (evt.type === 'game_over') return 'game-over'
  if (evt.type.startsWith('night_')) return 'night'
  return ''
}

// 自动滚动到底部
watch(() => gs.eventLog.length, async () => {
  await nextTick()
  if (timelineRef.value) {
    timelineRef.value.scrollTop = timelineRef.value.scrollHeight
  }
})

// 事件轮询
let pollTimer = null
function startPolling() {
  pollTimer = setInterval(() => {
    const events = drainEvents()
    for (const evt of events) {
      processEvent(evt)
    }
  }, 100)
}
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function startGame() {
  loading.value = true
  try {
    const resp = await fetch('/api/game/start', { method: 'POST' })
    const data = await resp.json()
    connect(data.game_id)
    startPolling()
  } catch (e) {
    console.error('Failed to start game:', e)
  }
  loading.value = false
}

function resetGame() {
  reset()
  disconnect()
  stopPolling()
}
</script>
