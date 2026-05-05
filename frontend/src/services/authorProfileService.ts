export interface AuthorProfile {
  display_name: string;
  profile_url?: string | null;
  avatar_url?: string | null;
}

export async function getAuthorProfile(): Promise<AuthorProfile> {
  const response = await fetch('/api/public/author-profile', {
    method: 'GET',
    credentials: 'include',
    cache: 'force-cache',
  });

  if (!response.ok) {
    throw new Error(`作者资料获取失败: ${response.status}`);
  }

  return response.json();
}
