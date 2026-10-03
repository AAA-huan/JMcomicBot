/** 当前登录管理员的漫画收藏接口。 */
import { apiRequest } from './client'

export interface FavoriteResult {
  manga_id: string
  is_favorite: boolean
  changed: boolean
}

export function setFavorite(mangaId: string, favorite: boolean): Promise<FavoriteResult> {
  return apiRequest(`/mangas/${encodeURIComponent(mangaId)}/favorite`, {
    method: favorite ? 'PUT' : 'DELETE',
  })
}
