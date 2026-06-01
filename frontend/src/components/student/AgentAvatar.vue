<template>
  <div class="avatar-group">
    <div class="avatar ai-avatar">
      <img :src="crabAvatar" alt="agent" class="avatar-img" />
    </div>
    <span class="agent-label">{{ agentLabel }}</span>
  </div>
</template>

<script setup>
import { inject } from 'vue'
import crabAvatar from '@/assets/卡通螃蟹头像2.png'
import { STUDENT_LEARNING_KEY } from '@/composables/useStudentLearning.js'

const { agentLabel } = inject(STUDENT_LEARNING_KEY)
</script>

<style scoped>
.avatar-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: bold;
  flex-shrink: 0;
  overflow: hidden;
}

.ai-avatar {
  background: linear-gradient(135deg, #dbeafe, #bfdbfe);
  color: #2563eb;
}

.avatar-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 50%;
}

.agent-label {
  font-size: 11px;
  color: #6b7280;
  font-weight: 500;
  white-space: nowrap;
}

@media (max-width: 640px) {
  .avatar {
    width: 30px;
    height: 30px;
  }

  .agent-label {
    font-size: 10px;
  }

  .avatar-group {
    gap: 2px;
  }
}
</style>
