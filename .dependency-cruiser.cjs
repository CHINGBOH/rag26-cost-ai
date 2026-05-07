/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  extends: 'dependency-cruiser/configs/recommended',
  forbidden: [
    {
      name: 'no-circular',
      comment: 'Circular dependencies hide runtime ownership and make cutovers risky.',
      severity: 'error',
      from: {},
      to: { circular: true },
    },
    {
      name: 'no-orphans',
      comment: 'Unused modules should either be wired into the topology or removed.',
      severity: 'warn',
      from: {
        orphan: true,
        path: '^src/',
        pathNot:
          '(^src/index\\.ts$|^src/main\\.tsx$|(^|.*/)__tests__/|\\.(test|spec)\\.(ts|tsx)$|\\.d\\.ts$)',
      },
      to: {},
    },
    {
      name: 'not-to-unresolvable',
      comment: 'Temporary suppression for the RxJS root import false-positive in the pipe module.',
      severity: 'ignore',
      from: {
        path: '^src/modules/common/pipe/src/index\\.ts$',
      },
    },
  ],
  options: {
    doNotFollow: { path: 'node_modules' },
    exclude: '(^dist/|^coverage/|^node_modules/)',
    tsPreCompilationDeps: true,
    tsConfig: { fileName: 'tsconfig.json' },
  },
};
