"use client";

import { useRef, useState } from "react";

import { Modal } from "./modal";

export function Confirm({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void | Promise<void>;
  onCancel: () => void;
}) {
  const [pending, setPending] = useState(false);
  const confirming = useRef(false);

  async function confirm() {
    if (confirming.current) return;
    confirming.current = true;
    setPending(true);
    try {
      await onConfirm();
    } finally {
      confirming.current = false;
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      title={title}
      onClose={pending ? () => {} : onCancel}
      footer={
        <div className="flex justify-end gap-2">
          <button type="button" autoFocus disabled={pending} className="btn btn-ghost" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button type="button" disabled={pending} className="btn btn-danger" onClick={confirm}>
            {confirmLabel}
          </button>
        </div>
      }
    >
      <p>{description}</p>
    </Modal>
  );
}
