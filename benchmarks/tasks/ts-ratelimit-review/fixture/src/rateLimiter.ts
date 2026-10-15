/**
 * Token-bucket rate limiter, one bucket per key (e.g. per API client).
 * `ratePerSecond` tokens are added every second, up to `capacity`.
 */
export class RateLimiter {
  private buckets: { [key: string]: { tokens: number; last: number } } = {};
  private readonly capacity: number;
  private readonly ratePerSecond: number;
  private readonly now: () => number;

  constructor(capacity: number, ratePerSecond: number, now: () => number = Date.now) {
    this.capacity = capacity;
    this.ratePerSecond = ratePerSecond;
    this.now = now;
  }

  /** Try to take one token for `key`. Returns true if the request is allowed. */
  allow(key: string): boolean {
    const t = this.now();
    let bucket = this.buckets[key];
    if (!bucket) {
      bucket = { tokens: this.capacity, last: t };
      this.buckets[key] = bucket;
    }
    const elapsed = t - bucket.last;
    bucket.tokens = bucket.tokens + elapsed * this.ratePerSecond;
    bucket.last = t;
    if (bucket.tokens >= 1) {
      bucket.tokens -= 1;
      return true;
    }
    return false;
  }
}
