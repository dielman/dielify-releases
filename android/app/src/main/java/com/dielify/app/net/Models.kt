package com.dielify.app.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// Mirrors the server's /api models (docs/openapi.json). Unknown fields are ignored, so
// the server can add fields without breaking older phones.

@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
    @SerialName("device_name") val deviceName: String,
)

@Serializable
data class LoginResult(
    val token: String,
    @SerialName("device_id") val deviceId: Int,
    val username: String,
    val profile: String,
)

@Serializable
data class Artist(
    val id: Long,
    val name: String,
    @SerialName("album_count") val albumCount: Int = 0,
    @SerialName("cover_url") val coverUrl: String? = null,
    val starred: Boolean = false,
)

@Serializable
data class Album(
    val id: Long,
    val name: String,
    val artist: String,
    @SerialName("artist_id") val artistId: Long,
    val year: Int? = null,
    @SerialName("song_count") val songCount: Int = 0,
    @SerialName("duration_s") val durationS: Int = 0,
    @SerialName("cover_url") val coverUrl: String? = null,
    val starred: Boolean = false,
)

@Serializable
data class Track(
    val id: Long,
    val title: String,
    val artist: String,
    val album: String,
    @SerialName("album_artist") val albumArtist: String = "",
    val year: Int? = null,
    @SerialName("track_no") val trackNo: Int? = null,
    @SerialName("duration_s") val durationS: Int? = null,
    @SerialName("bitrate_kbps") val bitrateKbps: Int? = null,
    val suffix: String = "",
    @SerialName("video_id") val videoId: String? = null,
    val starred: Boolean = false,
    @SerialName("stream_url") val streamUrl: String,
    @SerialName("cover_url") val coverUrl: String? = null,
)

@Serializable data class ArtistList(val artists: List<Artist>)
@Serializable data class AlbumList(val albums: List<Album>)
@Serializable data class ArtistDetail(val artist: Artist, val albums: List<Album>)
@Serializable data class AlbumDetail(val album: Album, val tracks: List<Track>)
@Serializable data class LibrarySearch(val artists: List<Artist>, val albums: List<Album>, val tracks: List<Track>)

// --- YouTube Music catalogue + downloads -------------------------------------------------

/** A song, video, album, playlist or artist on YouTube Music. */
@Serializable
data class Item(
    val type: String,                       // song | video | album | playlist | artist
    val id: String,                         // videoId, browseId, playlistId or channel id
    val title: String,
    val artists: List<String> = emptyList(),
    val album: String? = null,
    @SerialName("album_id") val albumId: String? = null,
    val year: String? = null,
    @SerialName("duration_s") val durationS: Int? = null,
    val thumbnail: String? = null,
    val subtitle: String? = null,
    @SerialName("library_track_id") val libraryTrackId: Long? = null,
) {
    val isSong get() = type == "song" || type == "video"
    val artistText get() = artists.joinToString(", ")
}

@Serializable data class Shelf(val title: String, val items: List<Item>)
@Serializable data class HomeFeed(val shelves: List<Shelf>)
@Serializable data class ItemList(val items: List<Item>)
@Serializable data class YtCollection(val info: Item, val tracks: List<Item>)

@Serializable
data class Charts(
    val country: String,
    val countries: List<String> = emptyList(),
    val playlists: List<Item> = emptyList(),
    val artists: List<Item> = emptyList(),
)

@Serializable
data class DownloadRequest(
    val type: String,
    val id: String,
    val title: String? = null,
    val artists: List<String> = emptyList(),
    val album: String? = null,
    val next: Boolean = false,
)

@Serializable
data class Download(
    val id: Long,
    @SerialName("video_id") val videoId: String,
    val title: String,
    val artist: String? = null,
    val album: String? = null,
    @SerialName("request_type") val requestType: String = "",
    @SerialName("request_title") val requestTitle: String? = null,
    val status: String,                     // queued | downloading | processing | done | failed | cancelled
    val progress: Double = 0.0,
    val error: String? = null,
    val attempts: Int = 0,
    @SerialName("track_id") val trackId: Long? = null,
    val next: Boolean = false,
) {
    val isActive get() = status == "queued" || status == "downloading" || status == "processing"
}

@Serializable
data class DownloadList(
    val downloads: List<Download>,
    @SerialName("active_total") val activeTotal: Int? = null,
    @SerialName("seconds_per_song") val secondsPerSong: Double? = null,
)

// --- play history + stats ---------------------------------------------------------------

@Serializable
data class PlayReport(
    @SerialName("track_id") val trackId: Long? = null,
    @SerialName("video_id") val videoId: String? = null,
    val title: String,
    val artist: String? = null,
    val album: String? = null,
    @SerialName("duration_s") val durationS: Int? = null,
    @SerialName("played_s") val playedS: Int,
    @SerialName("started_at") val startedAt: Double,
    @SerialName("client_id") val clientId: String,
)

@Serializable data class PlayBatch(val plays: List<PlayReport>)

@Serializable
data class StatSong(
    val title: String,
    val artist: String? = null,
    val album: String? = null,
    val plays: Int,
    val minutes: Int,
    @SerialName("track_id") val trackId: Long? = null,
    @SerialName("video_id") val videoId: String? = null,
    @SerialName("cover_url") val coverUrl: String? = null,
    val thumbnail: String? = null,
)

@Serializable
data class StatArtist(
    val name: String,
    val plays: Int,
    val minutes: Int,
    @SerialName("cover_url") val coverUrl: String? = null,
    @SerialName("artist_id") val artistId: Long? = null,
)

@Serializable
data class StatAlbum(
    val name: String,
    val artist: String? = null,
    val plays: Int,
    @SerialName("cover_url") val coverUrl: String? = null,
    @SerialName("album_id") val albumId: Long? = null,
)

@Serializable
data class Stats(
    val period: String,
    @SerialName("history_starts") val historyStarts: Double? = null,
    val plays: Int,
    val minutes: Int,
    val songs: Int,
    val artists: Int,
    val skips: Int,
    @SerialName("by_hour") val byHour: List<Int>,
    @SerialName("top_songs") val topSongs: List<StatSong>,
    @SerialName("top_artists") val topArtists: List<StatArtist>,
    @SerialName("top_albums") val topAlbums: List<StatAlbum>,
)

@Serializable
data class ForYou(
    @SerialName("on_repeat") val onRepeat: List<Track>,
    val forgotten: List<Track>,
    @SerialName("more_like") val moreLike: List<Item>,
)
