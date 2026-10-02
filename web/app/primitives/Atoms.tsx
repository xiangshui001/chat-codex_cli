// Adapted from DeepSeek Harness Button/Input/Pill at 639ed015397290b3745d163aafe02ffee4aa3f84.
// Copyright (c) 2026 DeepSeek. MIT; see ../third-party/DEEPSEEK-LICENSE.txt.
import {
  forwardRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from 'react';
import clsx from 'clsx';
import css from './Atoms.module.css';

export const Button = forwardRef<
  HTMLButtonElement,
  {
    variant?: 'primary' | 'ghost' | 'outline' | 'toolbar';
    size?: 'md' | 'sm';
    icon?: ReactNode;
  } & ButtonHTMLAttributes<HTMLButtonElement>
>(function Button({ variant = 'ghost', size = 'md', icon, className, children, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      className={clsx(css.button, css[variant], css[size], className)}
      {...rest}
    >
      {icon != null && <span className={css.icon}>{icon}</span>}
      {children}
    </button>
  );
});

export const Input = forwardRef<
  HTMLInputElement,
  {
    icon?: ReactNode;
  } & InputHTMLAttributes<HTMLInputElement>
>(function Input({ icon, className, ...rest }, ref) {
  return (
    <span className={clsx(css.wrap, className)}>
      {icon != null && <span className={css.icon}>{icon}</span>}
      <input ref={ref} className={css.input} {...rest} />
    </span>
  );
});

export function Pill({
  active = false,
  tone = 'neutral',
  className,
  children,
  onClick,
  ...rest
}: {
  active?: boolean;
  tone?: 'neutral' | 'green' | 'amber' | 'red' | 'blue';
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const style = clsx(css.pill, css[tone], active && css.active, className);
  return onClick ? (
    <button type="button" className={clsx(style, css.interactive)} onClick={onClick} {...rest}>
      {children}
    </button>
  ) : (
    <span className={style} title={rest.title}>
      {children}
    </span>
  );
}
