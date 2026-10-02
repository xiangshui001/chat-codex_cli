import { useEffect } from 'react';
import { ArrowRight, Code2, FileCheck2, ListTodo, Settings2 } from 'lucide-react';
import { Button, Pill } from '../primitives/Atoms';
import { LibraryModel } from '../features/LibraryModel';
import './login.css';

/** An unauthenticated UI preview, with a working transition to the mock workspace. */
export function LoginPage({ onEnter }: { onEnter: () => void }) {
  useEffect(() => {
    document.title = '欢迎 · chat-codex v2';
    try {
      document.documentElement.dataset.theme =
        localStorage.getItem('chat-codex-theme') === 'dark' ? 'dark' : 'light';
    } catch {
      /* Theme persistence is optional. */
    }
  }, []);
  return (
    <div className="login-page">
      <header className="login-header">
        <a className="login-brand" href="#/login" aria-label="chat-codex 欢迎页">
          <span className="brandmark">
            <Code2 size={19} />
          </span>
          <strong>
            chat-codex <small>v2</small>
          </strong>
        </a>
        <Pill>演示入口</Pill>
      </header>
      <main className="login-layout">
        <section className="login-copy" aria-labelledby="welcome-title">
          <div className="login-eyebrow">
            <span className="dot" />
            任务 · 模型 · 证据
          </div>
          <h1 id="welcome-title">
            你的 Codex
            <br />
            <span>协作工作区</span>
          </h1>
          <p className="login-description">
            集中查看任务、模型与执行证据，
            <br className="login-desktop-break" />
            保留每一次人工决定。
          </p>
          <div className="login-action">
            <Button variant="primary" onClick={onEnter}>
              进入演示工作区 <ArrowRight size={17} />
            </Button>
            <p>当前展示模拟任务与控制回执。</p>
          </div>
          <ul className="login-features">
            <li>
              <ListTodo size={17} />
              <div>
                <strong>任务进度</strong>
                <span>当前执行与待审候选，一览可见</span>
              </div>
            </li>
            <li>
              <Settings2 size={17} />
              <div>
                <strong>模型控制</strong>
                <span>每次更改都有明确的确认回执</span>
              </div>
            </li>
            <li>
              <FileCheck2 size={17} />
              <div>
                <strong>证据归档</strong>
                <span>任务合同、领取快照与检查摘要</span>
              </div>
            </li>
          </ul>
        </section>
        <div className="login-visual">
          <LibraryModel />
        </div>
      </main>
      <footer className="login-footer">
        <span>chat-codex · 可复核的执行与协作</span>
        <span>未登录页演示 · 登录服务尚未接入</span>
      </footer>
    </div>
  );
}
