import React from 'react'
import { runMaintenanceAction, maintenanceFailure } from '../maintenanceActions.mjs'

// Last-resort rendering protection, not a replacement for request/task handling.
export default class AppErrorBoundary extends React.Component {
  state = { failed: false, opening: false, message: '' }
  alive = true
  opening = false

  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch() { console.error('[UI_RENDER_FAILED] Application rendering failed; recovery screen shown.') }
  componentWillUnmount() { this.alive = false }
  componentDidMount() { this.alive = true }

  openLogs = async () => {
    if (this.opening) return
    this.opening = true
    this.setState({ opening: true, message: '' })
    try {
      await runMaintenanceAction('logs', { bridge: window.modagent })
      if (this.alive) this.setState({ message: 'opened' })
    } catch (error) {
      if (this.alive) this.setState({ message: error })
    } finally {
      this.opening = false
      if (this.alive) this.setState({ opening: false })
    }
  }

  render() {
    if (!this.state.failed) return this.props.children
    const language = document.documentElement.lang === 'en' ? 'en' : 'zh-CN'
    const ui = (zh, en) => language === 'en' ? en : zh
    const style = { padding: '12px 18px', border: '1px solid #70829c', borderRadius: 8, background: '#23334d', color: '#fff', cursor: 'pointer' }
    return <main role="alert" style={{minHeight:'100vh',boxSizing:'border-box',padding:'48px 24px',background:'#111827',color:'#e5e7eb',fontFamily:'system-ui,sans-serif',lineHeight:1.7}}>
      <section style={{maxWidth:720,margin:'0 auto'}}>
        <h1>{ui('界面遇到错误', 'The interface encountered an error')}</h1>
        <p>[UI_RENDER_FAILED]</p>
        <p>{ui('未能继续显示界面。此恢复页面不会清除已保存的配置或游戏文件。', 'The interface could not continue rendering. This recovery screen does not clear saved settings or game files.')}</p>
        <p>{ui('后台任务可能仍在运行。重新加载仅恢复界面，不代表取消或重做任务；恢复后请先核对任务和游戏状态，再执行操作。', 'Background tasks may still be running. Reloading only restores the interface; it does not cancel or repeat tasks. Check the task and game state before taking further action.')}</p>
        <p>{ui('未保存的输入可能已丢失。若错误反复出现，请保留错误代码、发生时间和操作步骤，并从日志目录获取诊断材料；分享前检查敏感信息。', 'Unsaved input may be lost. If this recurs, keep the error code, time and steps, and obtain diagnostics from the logs folder. Review sensitive information before sharing.')}</p>
        <div style={{display:'flex',gap:12,flexWrap:'wrap'}}>
          <button style={style} onClick={this.props.onReload || (() => window.location.reload())}>{ui('重新加载界面', 'Reload interface')}</button>
          <button style={style} disabled={this.state.opening} onClick={this.openLogs}>{this.state.opening ? ui('正在打开…', 'Opening…') : ui('打开日志目录', 'Open logs folder')}</button>
        </div>
        {this.state.message && <p role="status">{this.state.message === 'opened'
          ? ui('系统已确认打开日志目录，请检查文件窗口。', 'The system confirmed opening the logs folder. Check the file window.')
          : maintenanceFailure(this.state.message, language)}</p>}
      </section>
    </main>
  }
}
