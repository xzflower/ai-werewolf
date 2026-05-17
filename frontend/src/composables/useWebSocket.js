import { ref, computed } from 'vue'

/**
 * WebSocket 连接 composable
 */
export function useWebSocket() {
  const ws = ref(null)
  const connected = ref(false)
  const gameId = ref(null)
  const eventQueue = ref([])

  function connect(gid) {
    if (ws.value) return
    gameId.value = gid

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = location.host
    const url = `${protocol}//${host}/ws/${gid}`

    const socket = new WebSocket(url)
    socket.onopen = () => {
      connected.value = true
    }
    socket.onclose = () => {
      connected.value = false
      ws.value = null
    }
    socket.onmessage = (msg) => {
      try {
        const event = JSON.parse(msg.data)
        eventQueue.value.push(event)
      } catch (e) {
        console.error('Failed to parse WS message:', e)
      }
    }
    socket.onerror = (e) => {
      console.error('WS error:', e)
    }
    ws.value = socket
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
    connected.value = false
  }

  function drainEvents() {
    const events = [...eventQueue.value]
    eventQueue.value = []
    return events
  }

  return { ws, connected, gameId, eventQueue, connect, disconnect, drainEvents }
}
