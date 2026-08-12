// SkinnedMesh-safe clone for imported assets.
export function cloneWithSkeletons(source) {
  if (!source?.isObject3D) return source ? source.clone?.(true) ?? null : null;

  const sourceByClone = new Map();
  const cloneBySource = new Map();
  const clonedRoot = source.clone(true);

  parallelTraverse(source, clonedRoot, (srcNode, dstNode) => {
    sourceByClone.set(dstNode, srcNode);
    cloneBySource.set(srcNode, dstNode);
  });

  clonedRoot.traverse((dstNode) => {
    if (!dstNode?.isSkinnedMesh) return;
    const srcNode = sourceByClone.get(dstNode);
    if (!srcNode?.skeleton) return;

    const srcBones = srcNode.skeleton.bones || [];
    const dstSkeleton = srcNode.skeleton.clone();
    dstSkeleton.bones = srcBones.map((srcBone) => cloneBySource.get(srcBone)).filter(Boolean);
    dstNode.bind(dstSkeleton, srcNode.bindMatrix);
  });

  return clonedRoot;
}

function parallelTraverse(src, dst, callback) {
  callback(src, dst);
  const srcChildren = src.children || [];
  const dstChildren = dst.children || [];
  const count = Math.min(srcChildren.length, dstChildren.length);
  for (let i = 0; i < count; i += 1) {
    parallelTraverse(srcChildren[i], dstChildren[i], callback);
  }
}
