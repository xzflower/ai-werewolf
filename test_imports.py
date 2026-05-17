"""完整验证游戏引擎各模块"""
import sys
sys.path.insert(0, '/home/ubuntu/ai-werewolf')

from backend.game.models import Role, Camp, Phase, GameConfig, BeliefEntry
from backend.game.roles import create_players, ROLE_DESCRIPTIONS
from backend.agent.memory import AgentMemory
from backend.agent.base import AgentBase
from backend.llm.client import LLMClient

print("=" * 50)
print("🧪 AI 狼人杀 - 模块验证")
print("=" * 50)

# 1. Models
print("\n📦 models:")
for r in Role:
    print(f"  {r.value} -> {r.display_name()}")
print(f"  Phases: {len(list(Phase))}")

# 2. Roles
players = create_players()
roles_count = {}
for p in players:
    roles_count[p.role] = roles_count.get(p.role, 0) + 1
print(f"\n🎭 角色分配 ({len(players)}人):")
for r, c in sorted(roles_count.items(), key=lambda x: x[0].value):
    print(f"  {r.display_name()}: {c}人")

# 3. Memory
mem = AgentMemory()
mem.update_belief(BeliefEntry(player_id=2, guessed_role="狼人", confidence=0.8, reason="投票可疑"))
mem.update_belief(BeliefEntry(player_id=5, guessed_role="预言家", confidence=0.6, reason="发言逻辑清晰"))
print(f"\n🧠 记忆系统:")
print(f"  {mem.summarize_beliefs()[:120]}...")

# 4. LLM
llm = LLMClient()
print(f"\n🔌 LLM 客户端:")
print(f"  模型: {llm.model}")
print(f"  API Key: {'✅ 已配置' if llm.api_key else '❌ 未配置'}")

# 5. Agent
agent = AgentBase(player_id=1, name="玩家1", role=Role.VILLAGER, camp=Camp.VILLAGER, llm=llm)
prompt = agent.build_system_prompt()
print(f"\n🤖 Agent 示例 (平民):")
print(f"  System prompt 长度: {len(prompt)} 字符")
print(f"  开头: {prompt[:80]}...")

agent_wolf = AgentBase(player_id=2, name="玩家2", role=Role.WEREWOLF, camp=Camp.WEREWOLF, llm=llm)
prompt_wolf = agent_wolf.build_system_prompt()
print(f"\n🐺 Agent 示例 (狼人):")
print(f"  System prompt 长度: {len(prompt_wolf)} 字符")
print(f"  包含狼队友: {'狼人队友' in prompt_wolf}")

# 6. GM
from backend.game.gm import GameMaster
gm = GameMaster()
gm.init_game()
print(f"\n🎮 Game Master:")
print(f"  玩家数: {len(gm.state.players)}")
print(f"  Agent 数: {len(gm.agents)}")

print("\n" + "=" * 50)
print("✅ 所有模块验证通过!")
print("=" * 50)
