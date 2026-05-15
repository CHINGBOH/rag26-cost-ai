import type { CodeChannel, CodeProvider, SendCodeRequest, SendCodeResult } from './types';

export class MockCodeProvider implements CodeProvider {
  public readonly name = 'mock';
  public sent: SendCodeRequest[] = [];

  constructor(public readonly channel: CodeChannel) {}

  async send(req: SendCodeRequest): Promise<SendCodeResult> {
    this.sent.push(req);
    console.log(
      `[MockCodeProvider/${this.channel}] → recipient=${req.recipient} code=${req.code} purpose=${req.purpose}`,
    );
    return { success: true, provider: this.name, messageId: `mock-${Date.now()}` };
  }
}
