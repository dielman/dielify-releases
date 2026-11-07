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
