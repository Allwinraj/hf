import { Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing'
import Overview from './pages/Overview'
import SkillLibrary from './pages/SkillLibrary'
import CreateAgent from './pages/CreateAgent'
import SuperAgents from './pages/SuperAgents'
import AgentChat from './pages/AgentChat'
import RunDetail from './pages/RunDetail'

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/architect" element={<Overview />} />
      <Route path="/architect/skills" element={<SkillLibrary />} />
      <Route path="/architect/create" element={<CreateAgent />} />
      <Route path="/agents" element={<SuperAgents />} />
      <Route path="/agents/:agentId" element={<AgentChat />} />
      <Route path="/runs/:runId" element={<RunDetail />} />
    </Routes>
  )
}
