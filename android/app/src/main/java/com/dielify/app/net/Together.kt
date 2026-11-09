package com.dielify.app.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

// 0.9.8 Together: Blend and Jam (see dielify/blend.py, dielify/jam.py).

@Serializable
data class BlendPlaylist(val id: Long, val name: String)

@Serializable
data class BlendState(
    val on: Boolean,
    val allowed: Boolean,
    val partners: List<String>,
    @SerialName("waiting_for") val waitingFor: List<String>,
    val playlists: List<BlendPlaylist>,
)

@Serializable
data class BlendIn(val on: Boolean)

@Serializable
data class ShareIn(val shared: Boolean)

@Serializable
data class JamSong(val id: Long, val item: Item, @SerialName("added_by") val addedBy: String)

@Serializable
data class Jam(
    val host: String,
    val device: String,
    @SerialName("you_host") val youHost: Boolean,
    val members: List<String>,
    @SerialName("started_at") val startedAt: Double,
    val index: Int,
    val version: Int,
    val songs: List<JamSong>,
    @SerialName("left_out") val leftOut: List<String> = emptyList(),
)

/** A song for the Jam (same shape as a download request). */
@Serializable
data class JamSongIn(
    val type: String = "song",
    val id: String,
    val title: String? = null,
    val artists: List<String> = emptyList(),
    val album: String? = null,
)

@Serializable
data class JamStart(val device: String, val songs: List<JamSongIn> = emptyList())

@Serializable
data class JamAdd(val songs: List<JamSongIn>)

@Serializable
data class JamPlaying(val index: Int)
