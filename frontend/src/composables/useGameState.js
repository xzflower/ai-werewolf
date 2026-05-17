import { reactive, computed } from 'vue'

/**
 * 狼人杀游戏状态管理器
 * 接收 WebSocket 事件流，维护完整游戏状态
 */
export function useGameState() {
  const state = reactive({
    players: [],           // {id, name, role, camp, alive, seat}
    phase: 'lobby',        // 当前阶段
    round: 0,
    dayCount: 0,
    gameOver: false,
    winner: null,

    // 事件日志（用于时间线展示）
    eventLog: [],

    // 当前阶段数据
    currentSpeech: null,   // 当前发言
    currentVotes: {},      // 当前投票
    voteTally: {},
    currentNightAction: null,
    nightDeaths: [],
    eliminationHistory: [],
    seerResults: [],
    wolfChats: [],
    hunterShot: null,

    // 统计数据
    roleMap: {},           // id -> role name
    aliveCount: 0,
    wolfCount: 0,
  })

  const phaseLabel = computed(() => {
    const labels = {
      lobby: '大厅',
      night_werewolf: '🌙 狼人行动',
      night_seer: '🔮 预言家查验',
      night_witch: '🧪 女巫行动',
      night_guard: '🛡️ 守卫守护',
      day_announce: '📢 天亮公告',
      day_speech: '☀️ 白天发言',
      day_vote: '🗳 投票',
      vote_result: '📊 投票结果',
      hunter_shot: '🏹 猎人开枪',
      game_over: '🏁 游戏结束',
    }
    return labels[state.phase] || state.phase
  })

  function addLog(type, data, label = '') {
    state.eventLog.push({
      type,
      data,
      label,
      time: Date.now(),
      round: state.round,
    })
  }

  function processEvent(event) {
    const { type, data } = event

    switch (type) {
      case 'game_init': {
        // 初始化玩家信息
        const existing = state.players.find(p => p.id === data.player_id)
        if (!existing) {
          state.players.push({
            id: data.player_id,
            name: data.player_name,
            role: data.role,
            camp: data.camp,
            alive: true,
            seat: data.player_id,
          })
          state.roleMap[data.player_id] = data.role
        }
        state.aliveCount = state.players.filter(p => p.alive).length
        break
      }

      case 'game_start':
        state.phase = 'night_werewolf'
        addLog('game_start', data, '🎮 游戏开始')
        break

      case 'phase_change': {
        state.phase = data.phase
        // 清理阶段性数据
        if (data.phase.startsWith('night_')) {
          state.currentNightAction = null
          state.wolfChats = []
        }
        if (data.phase === 'day_speech') {
          state.currentSpeech = null
        }
        if (data.phase === 'day_vote') {
          state.currentVotes = {}
          state.voteTally = {}
        }
        addLog('phase_change', data, `阶段变更: ${phaseLabel.value}`)
        break
      }

      case 'speech': {
        state.currentSpeech = {
          playerId: data.player_id,
          playerName: data.player_name,
          content: data.content,
          innerMonologue: data.inner_monologue || '',
          round: data.round,
        }
        addLog('speech', data, `🗣 ${data.player_name} 发言`)
        break
      }

      case 'wolf_chat': {
        state.wolfChats.push({
          playerId: data.player_id,
          content: data.content,
        })
        addLog('wolf_chat', data, `🐺 狼人私聊`)
        break
      }

      case 'night_action': {
        const role = state.roleMap[data.player_id] || ''
        let label = `⚔️ ${data.action_type}`
        if (role === 'seer') label = '🔮 预言家查验'
        if (role === 'witch') label = '🧪 女巫行动'
        if (role === 'guard') label = '🛡️ 守卫守护'
        addLog('night_action', data, label)
        break
      }

      case 'night_result': {
        state.nightDeaths = data.deaths || []
        addLog('night_result', data, `🌙 夜晚结算`)
        break
      }

      case 'seer_result': {
        state.seerResults.push({
          targetId: data.target_id,
          targetName: data.target_name,
          camp: data.camp,
          round: data.round || state.round,
        })
        addLog('seer_result', data, `🔮 查验结果`)
        break
      }

      case 'vote_result': {
        state.currentVotes = data.votes || {}
        state.voteTally = data.tally || {}
        addLog('vote_result', data, `📊 投票结果`)
        break
      }

      case 'elimination': {
        const player = state.players.find(p => p.id === data.player_id)
        if (player) {
          player.alive = false
          player.revealed = true
        }
        state.eliminationHistory.push(data)
        state.aliveCount = state.players.filter(p => p.alive).length
        state.wolfCount = state.players.filter(p => p.alive && p.role === 'werewolf').length
        const roleLabel = state.roleMap[data.player_id] || ''
        addLog('elimination', data, `⚰️ ${data.player_name} (${roleLabel}) 出局 - ${data.cause}`)
        break
      }

      case 'hunter_shot': {
        state.hunterShot = data
        addLog('hunter_shot', data, `🏹 ${data.player_name} 开枪`)
        break
      }

      case 'game_over': {
        state.gameOver = true
        state.winner = data.winner
        state.phase = 'game_over'
        addLog('game_over', data, `🏁 游戏结束！${data.winner === 'werewolf' ? '🐺 狼人获胜' : '👼 好人获胜'}`)
        break
      }
    }
  }

  function reset() {
    state.players = []
    state.phase = 'lobby'
    state.round = 0
    state.dayCount = 0
    state.gameOver = false
    state.winner = null
    state.eventLog = []
    state.currentSpeech = null
    state.currentVotes = {}
    state.voteTally = {}
    state.currentNightAction = null
    state.nightDeaths = []
    state.eliminationHistory = []
    state.seerResults = []
    state.wolfChats = []
    state.hunterShot = null
    state.roleMap = {}
    state.aliveCount = 0
    state.wolfCount = 0
  }

  return { state, phaseLabel, processEvent, reset }
}
